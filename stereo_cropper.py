#!/usr/bin/env python

# Copyright 2016 Ian Munsie
#
# This file is part of the Stereo Cropping Tool.
#
# The Stereo Cropping Tool is free software: you can redistribute it and/or
# modify it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# The Stereo Cropping Tool is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General
# Public License for more details.
#
# You should have received a copy of the GNU General Public License along with
# The Stereo Cropping Tool. If not, see <http://www.gnu.org/licenses/>.

from __future__ import print_function

import sys, os
import ctypes, struct, math
import numpy as np
from collections import namedtuple
import Tkinter, tkFileDialog

from directx.types import *
from directx.util import Frame
from directx.d3d import IDirect3DVertexBuffer9, IDirect3DTexture9

from nvapi import *

import PIL
from PIL import Image
# Ensure this is a recent version of the pillow fork with support for stereo .mpo files
# Haven't checked which version it was introduced in, don't really care either.
assert(hasattr(PIL, 'PILLOW_VERSION') and map(int, PIL.PILLOW_VERSION.split('.')) >= [3, 3, 0])

backgrounds = (
    0x000000,
    0xffffff,
    0xc0c0c0,
    0x808080,
    0x404040,
    #0x84807c, # Warm gray
    #0x7c8084, # Cool gray
)

# Custom vertex and it's FVF code. This is outdated tech for fixed pipeline, we
# might change it later.
class Vertex(Structure):
    _fields_ = [
        ('x', c_float),
        ('y', c_float),
        ('z', c_float),
        ('rhw', c_float),
        ('u', c_float),
        ('v', c_float),
    ]

VERTEXFVF = D3DFVF.XYZRHW | D3DFVF.TEX2

class MODES:
    DEFAULT = 0
    PARALLAX = 1
    CROP = 2
    CROP_LEFT = 3
    CROP_RIGHT = 4
    CROP_TOP = 5
    CROP_BOTTOM = 6
    hold_keys = {
            ord('P'): PARALLAX,
            ord('C'): CROP,
            0x11: CROP, # VK_CONTROL
    }

ImageRect = namedtuple('ImageRect', ['x', 'y', 'w', 'h', 'u1', 'v1', 'u2', 'v2'])

def saturate(n):
    return min(max(n, 0.0), 1.0)

# The Frame class from the util module is not an ideal fit for my needs, but it
# will work and will save time so I'll use it for now.
class CropTool(Frame):
    def __init__(self, filename, *a, **kw):
        self.filename = filename
        self.scale = 1.0
        self.mouse_last = None
        self.mode = MODES.DEFAULT
        self.pan = (0, 0)
        self.parallax = 0.0
        self.vcrop = [0.0, 1.0]
        self.hcrop = [[0.0, 1.0], [0.0, 1.0]]
        self.background = backgrounds[0]
        self.dirty = False
        return Frame.__init__(self, *a, **kw)

    def image_to_texture(self, image):
        texture = POINTER(IDirect3DTexture9)()
        # Seems we must use a 32bpp format for hardware support:
        self.device.CreateTexture(image.width, image.height, 1, 0, D3DFORMAT.X8R8G8B8, D3DPOOL.MANAGED, byref(texture), None)

        rect = D3DLOCKED_RECT()
        texture.LockRect(0, byref(rect), None, D3DLOCK.DISCARD)

        # Convert B8G8R8 -> X8R8G8B8, using numpy for speed and directly using
        # the destination buffer to minimise excess copies. This seems to be
        # significantly faster than even using self.LoadTexture / D3DX, so
        # that's an unexpected win:
        np_src_buf = np.frombuffer(image.tobytes(), np.uint8).reshape(image.width * image.height, 3)
        dst_buf = (c_uint8 * image.width * image.height * 4).from_address(rect.pBits)
        np_dst_buf = np.frombuffer(dst_buf, np.uint8).reshape(image.width * image.height, 4)
        np_dst_buf[:,:-1] = np_src_buf[:,[2,1,0]]

        texture.UnlockRect(0)

        return texture

    def get_image_eye(self, eye):
        self.image_height = self.image.height
        if self.image.format == 'MPO':
            self.image.seek(eye == 1)
            self.image_width = self.image.width
            return self.image
        elif self.image.format == 'JPEG':
            self.image_width = self.image.width / 2
            x = 0
            if eye != 1:
                x = self.image_width
            return self.image.crop((x, 0, x + self.image_width, self.image_height))
        else:
            print('Unsupported image type: %s' % self.image.format)
            sys.exit(1)

    def load_stereo_image(self, filename):
        self.image = Image.open(filename)

        texture_l = self.image_to_texture(self.get_image_eye(0))
        texture_r = self.image_to_texture(self.get_image_eye(1))

        # FIXME: Read parallax tag from *second image's* EXIF info - this does
        # not seem to be available in Pillow yet.

        return texture_l, texture_r

    def save_adjusted_jps(self):
        base_filename = os.path.splitext(self.filename)[0] + '-cropped'
        filename = base_filename + '.jps'
        i = 0
        while os.path.exists(filename):
            i += 1
            filename = base_filename + '-%d.jps' % i

        l_offset = self.hcrop[0][0] - self.parallax / 200.0
        r_offset = self.hcrop[1][0] + self.parallax / 200.0

        # Align one of the two images to the left of the final image:
        if l_offset < r_offset:
            r_offset -= l_offset
            l_offset = 0.0
        else:
            l_offset -= r_offset
            r_offset = 0.0

        # Calculate the width taking cropping and parallax into account. The
        # width will be the maximum required for the two images, but no more -
        # one of the images should be aligned to the right.
        width = int(math.ceil(max(self.hcrop[0][1] - self.hcrop[0][0] + l_offset, self.hcrop[1][1] - self.hcrop[1][0] + r_offset) * self.image_width))
        height = (self.vcrop[1] - self.vcrop[0]) * self.image_height

        byteswapped_background = struct.unpack('<I', struct.pack('>I', self.background))[0] >> 8
        new_img = Image.new(self.image.mode, (width * 2, int(round(height))), byteswapped_background)

        image = self.get_image_eye(0)
        l_img = image.crop((
            self.hcrop[0][0] * image.width,
            self.vcrop   [0] * image.height,
            self.hcrop[0][1] * image.width,
            self.vcrop   [1] * image.height))
        new_img.paste(l_img, (width + int(round(l_offset * image.width)), 0))
        l_img.close()

        image = self.get_image_eye(1)
        r_img = image.crop((
            self.hcrop[1][0] * image.width,
            self.vcrop   [0] * image.height,
            self.hcrop[1][1] * image.width,
            self.vcrop   [1] * image.height))
        new_img.paste(r_img, (int(round(r_offset * image.width)), 0))
        r_img.close()

        new_img.save(filename, format='JPEG')
        new_img.close()
        self.dirty = False

    def OnCreateDevice(self):
        self.stereo_handle = c_void_p()
        NvAPI.Stereo_CreateHandleFromIUnknown(self.device, byref(self.stereo_handle))

        # Load both images from the MPO file into a pair of textures:
        self.texture_l, self.texture_r = self.load_stereo_image(self.filename)

        # Create two vertex buffers for the images in each eye. Later we might
        # switch to the programmable pipeline and work out the offsets in the
        # vertex shader instead, but for now this is easier
        self.vbuffer_l = POINTER(IDirect3DVertexBuffer9)()
        self.vbuffer_r = POINTER(IDirect3DVertexBuffer9)()
        self.device.CreateVertexBuffer(sizeof(Vertex) * 4, 0, 0,
            D3DPOOL.MANAGED, byref(self.vbuffer_l), None)
        self.device.CreateVertexBuffer(sizeof(Vertex) * 4, 0, 0,
            D3DPOOL.MANAGED, byref(self.vbuffer_r), None)

    def OnDestroyDevice(self):
        del self.texture_l
        del self.texture_r
        del self.vbuffer_l
        del self.vbuffer_r

    def fit_to_window(self):
        res_a = float(self.presentparams.BackBufferWidth) / self.presentparams.BackBufferHeight
        a = float(self.image_width) / self.image_height
        if a > res_a:
            self.scale = float(self.presentparams.BackBufferWidth) / self.image_width
        else:
            self.scale = float(self.presentparams.BackBufferHeight) / self.image_height
        self.pan = (0, 0)

    def OnInit(self):
        self.ToggleFullscreen()
        self.fit_to_window()

    def cycle_background_colours(self):
        self.background = backgrounds[(backgrounds.index(self.background) + 1) % len(backgrounds)]

    def OnKey(self, (msg, wParam, lParam)):
        if msg == 0x100 and not lParam & 0x40000000: # WM_KEYDOWN that is not a repeat
            # Borrow some geeqie style key bindings, and some custom ones
            if wParam == 0x1B: # Escape
                if self.dirty:
                    self.save_adjusted_jps()
                self.Quit()
            elif wParam == ord('Z'):
                self.scale = 1.0
                self.pan = (0, 0)
            elif wParam == ord('X'):
                self.fit_to_window()
            elif wParam == ord('F'):
                self.ToggleFullscreen()
                self.fit_to_window()
            elif wParam == ord('S'):
                self.save_adjusted_jps()
            elif wParam == ord('B'):
                self.cycle_background_colours()
            elif wParam in MODES.hold_keys:
                self.mode = MODES.hold_keys[wParam]
        elif msg == 0x105 and not lParam & 0x40000000: # WM_SYSKEYDOWN that is not a repeat:
            if wParam == 0x79: # F10
                self.ToggleFullscreen()
                self.fit_to_window()
        elif msg == 0x101: # WM_KEYUP
            if wParam in MODES.hold_keys:
                self.mode = MODES.DEFAULT

    def OnMouse(self, (msg, x, y, wheel, modifiers)):
        if msg in (0x201, 0x204, 0x207): # Mouse down left/right/middle
            if self.mode == MODES.CROP:
                xa = (self.rect_l.x + self.rect_r.x) / 2.0
                wa = (self.rect_l.w + self.rect_r.w) / 2.0
                if wa <= 0: # Divide by zero protection
                    if x > xa:
                        self.mode = MODES.CROP_RIGHT
                    else:
                        self.mode = MODES.CROP_LEFT
                elif self.rect_l.h <= 0:
                    if y > self.rect_l.x:
                        self.mode = MODES.CROP_BOTTOM
                    else:
                        self.mode = MODES.CROP_TOP
                else:
                    xp = float(x - xa) / wa
                    yp = float(y - self.rect_l.y) / self.rect_l.h
                    if xp > yp: # Top / Right
                        if xp > 1 - yp:
                            self.mode = MODES.CROP_RIGHT
                        else:
                            self.mode = MODES.CROP_TOP
                    else: # Bottom / Left
                        if xp > 1 - yp:
                            self.mode = MODES.CROP_BOTTOM
                        else:
                            self.mode = MODES.CROP_LEFT
        elif msg in (0x202, 0x205, 0x208): # Mouse up left/right/middle
            if self.mode in (MODES.CROP_LEFT, MODES.CROP_RIGHT, MODES.CROP_TOP, MODES.CROP_BOTTOM):
                self.mode = MODES.CROP
        elif msg == 0x20a: # Mouse wheel
            self.scale = max(self.scale * (1.0 + wheel / 900.0), 0.025)
        elif msg == 0x200: # Mouse move
            if self.mouse_last is None:
                dx = dy = dix = diy = 0
            else:
                dx = x - self.mouse_last[0]
                dy = y - self.mouse_last[1]
                dix = dx / self.scale / self.image_width
                diy = dy / self.scale / self.image_height
            self.mouse_last = x, y
            if self.mode == MODES.DEFAULT:
                if modifiers & 0x0001: # Left button down - panning
                    self.pan = self.pan[0] + dx, self.pan[1] + dy
                if modifiers & 0x0010: # Middle button down - parallax adjustment
                    self.parallax += dy / self.scale / self.image_height * 100.0
                    self.dirty = True
            elif self.mode == MODES.PARALLAX:
                if modifiers & 0x0001: # Left button down
                    self.parallax += dix * 200.0
                    self.dirty = True
                elif modifiers & 0x0002: # Right button down
                    self.parallax -= dix * 200.0
                    self.dirty = True
            elif self.mode == MODES.CROP_TOP:
                if modifiers & 0x0013: # Any button down
                    self.vcrop[0] = min(saturate(self.vcrop[0] + diy), self.vcrop[1])
                    self.dirty = True
            elif self.mode == MODES.CROP_BOTTOM:
                if modifiers & 0x0013: # Any button down
                    self.vcrop[1] = max(saturate(self.vcrop[1] + diy), self.vcrop[0])
                    self.dirty = True
            elif self.mode == MODES.CROP_LEFT:
                if modifiers & 0x0001: # Left button down - crop left/right
                    self.hcrop[1][0] = min(saturate(self.hcrop[1][0] + dix), self.hcrop[1][1])
                    self.hcrop[0][0] = min(saturate(self.hcrop[0][0] + dix), self.hcrop[0][1])
                    self.dirty = True
                elif modifiers & 0x0002: # Right buttons down - move up/down to crop back/forward
                    self.hcrop[1][0] = min(saturate(self.hcrop[1][0] - diy / 2.0), self.hcrop[1][1])
                    self.hcrop[0][0] = min(saturate(self.hcrop[0][0] + diy / 2.0), self.hcrop[0][1])
                    self.dirty = True
            elif self.mode == MODES.CROP_RIGHT:
                if modifiers & 0x0001: # Left button down - crop left/right
                    self.hcrop[1][1] = max(saturate(self.hcrop[1][1] + dix), self.hcrop[1][0])
                    self.hcrop[0][1] = max(saturate(self.hcrop[0][1] + dix), self.hcrop[0][0])
                    self.dirty = True
                elif modifiers & 0x0002: # Right buttons down - move up/down to crop back/forward
                    self.hcrop[1][1] = max(saturate(self.hcrop[1][1] - diy / 2.0), self.hcrop[1][0])
                    self.hcrop[0][1] = max(saturate(self.hcrop[0][1] + diy / 2.0), self.hcrop[0][0])
                    self.dirty = True

    def calc_rect(self, eye):

        # Crop
        u1 = self.hcrop[eye == 1.0][0]
        v1 = self.vcrop[0]
        u2 = self.hcrop[eye == 1.0][1]
        v2 = self.vcrop[1]

        x = self.hcrop[eye == 1.0][0]
        y = self.vcrop[0]
        w = self.hcrop[eye == 1.0][1] - self.hcrop[eye == 1.0][0]
        h = self.vcrop[1] - self.vcrop[0]

        # Parallax
        x += eye / 2.0 * self.parallax / 100.0

        # Scale
        iw = self.image_width * self.scale
        ih = self.image_height * self.scale
        w = w * iw
        h = h * ih
        x = x * self.image_width * self.scale + (self.presentparams.BackBufferWidth - iw) / 2
        y = y * self.image_height * self.scale + (self.presentparams.BackBufferHeight - ih) / 2

        # Pan
        x, y = x + self.pan[0], y + self.pan[1]

        return ImageRect(x, y, w, h, u1, v1, u2, v2)

    def update_vertex_buffer_eye(self, vbuffer, r):
        # Update the vertex buffer with the vertex positions and texture
        # coordinates that correspond to the current paralax and crop
        ptr = c_void_p()
        vbuffer.Lock(0, 0, byref(ptr), 0)

        data = (Vertex * 4)(
            #            X        Y  Z  RHW     U     V
            Vertex(    r.x,     r.y, 1, 1.0, r.u1, r.v1),
            Vertex(r.x+r.w,     r.y, 1, 1.0, r.u2, r.v1),
            Vertex(    r.x, r.y+r.h, 1, 1.0, r.u1, r.v2),
            Vertex(r.x+r.w, r.y+r.h, 1, 1.0, r.u2, r.v2),
        )
        ctypes.memmove(ptr, data, sizeof(Vertex) * 4)
        vbuffer.Unlock()

    def OnUpdate(self):
        self.rect_l = self.calc_rect(-1)
        self.rect_r = self.calc_rect( 1)
        self.update_vertex_buffer_eye(self.vbuffer_l, self.rect_l)
        self.update_vertex_buffer_eye(self.vbuffer_r, self.rect_r)

    def OnRender(self):
        self.device.SetFVF(VERTEXFVF)

        NvAPI.Stereo_SetActiveEye(self.stereo_handle, STEREO_ACTIVE_EYE.LEFT)
        self.device.Clear(0, None, D3DCLEAR.TARGET | D3DCLEAR.ZBUFFER, 0xff000000 | self.background, 1.0, 0)
        self.device.SetStreamSource(0, self.vbuffer_l, 0, sizeof(Vertex))
        self.device.SetTexture(0, self.texture_l)
        self.device.DrawPrimitive(D3DPT.TRIANGLESTRIP, 0, 2)

        NvAPI.Stereo_SetActiveEye(self.stereo_handle, STEREO_ACTIVE_EYE.RIGHT)
        self.device.Clear(0, None, D3DCLEAR.TARGET | D3DCLEAR.ZBUFFER, 0xff000000 | self.background, 1.0, 0)
        self.device.SetStreamSource(0, self.vbuffer_r, 0, sizeof(Vertex))
        self.device.SetTexture(0, self.texture_r)
        self.device.DrawPrimitive(D3DPT.TRIANGLESTRIP, 0, 2)

def enable_stereo_in_windowed_mode():
    # We are using DirectX 9 to allow for the possibility of stereo in
    # windowed mode (which is not possible in DX11). For this to work,
    # StereoProfile=1 must be saved into a driver profile for python.exe.
    # The below code is a start, but applies it to the base profile
    # instead (which doesn't seem to work). This also will need the program
    # to request admin privileges, and may need a restart after applying it.
    # Question is, how to apply this specifically to this instance of
    # python.exe, but no others? The driver profiles really are a silly design.

    # A workaround is to start in full screen mode, disable the stereo memo
    # with Ctrl+Alt+Insert, which since python.exe is not in any predefined
    # profiles will create a new stereo profile for it, allowing stereo to work
    # in windowed mode from that point onwards.

    # A second workaround is to use an existing stereo profile with the
    # settings we need, but this only works if python.exe is not already in a
    # profile. 3D-Hub Player is a good choice as it is a Stereo Profile without
    # any other stereo settings that could interfere with us. The biggest
    # problem with this approach is that the stereo memo is misleading, and it
    # may stop working if a future driver adds a profile for python.exe without
    # the StereoProfile setting, but this will do for now:
    try:
        NvAPI.Stereo_SetDefaultProfile('fxdplayer')
    except NvAPI_Exception as e:
        print('Unable to set default stereo profile: %s' % str(e))

    # drs_handle = c_void_p()
    # drs_profile = c_void_p()
    # NvAPI.DRS_CreateSession(byref(drs_handle))
    # NvAPI.DRS_LoadSettings(drs_handle)
    # NvAPI.DRS_GetBaseProfile(drs_handle, byref(drs_profile))
    # setting = NVDRS_SETTING()
    # setting.version = MAKE_NVAPI_VERSION(NVDRS_SETTING, 1)
    # setting.settingId = 0x701EB457 # StereoProfile
    # setting.settingType = 0
    # setting.current.u32Value = 1
    # NvAPI.DRS_SetSetting(drs_handle, drs_profile, byref(setting))
    # setting.settingId = 0x707F4B45 # StereoMemoEnabled
    # setting.current.u32Value = 0
    # NvAPI.DRS_SetSetting(drs_handle, drs_profile, byref(setting))
    # NvAPI.DRS_SaveSettings(drs_handle)
    # NvAPI.DRS_DestroySession(drs_handle)

def main():
    try:
        filename = sys.argv[1]
    except IndexError:
        root = Tkinter.Tk()
        root.withdraw()
        filename = tkFileDialog.askopenfilename(filetypes = [
            ('Stereo Images', ('.mpo', '.jps')),
            ('MPO files', '.mpo'),
            ('JPS files', '.jps'),
            ('All files', '*')
            ])
        if not filename:
            return

    NvAPI.Initialize()
    enable_stereo_in_windowed_mode()
    NvAPI.Stereo_SetDriverMode(STEREO_DRIVER_MODE.DIRECT)

    f = CropTool(filename, "Stereo Photo Cropping Tool")
    f.Mainloop()

    NvAPI.Unload()

if __name__ == '__main__':
    main()

# vi:et:sw=4:ts=4
