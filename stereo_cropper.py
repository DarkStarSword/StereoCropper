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

from directx.types import *
from directx.util import Frame
from directx.d3d import IDirect3DVertexBuffer9, IDirect3DTexture9

import ctypes

from nvapi import *

import PIL
from PIL import Image
# Ensure this is a recent version of the pillow fork with support for stereo .mpo files
# Haven't checked which version it was introduced in, don't really care either.
assert(hasattr(PIL, 'PILLOW_VERSION') and map(int, PIL.PILLOW_VERSION.split('.')) >= [3, 3, 0])

import numpy as np

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

    def load_stereo_mpo(self, filename):
        self.image = Image.open(filename)
        texture_l = self.image_to_texture(self.image)
        self.image.seek(1)
        texture_r = self.image_to_texture(self.image)

        # FIXME: Read parallax tag from *second image's* EXIF info - this does
        # not seem to be available in Pillow yet.

        self.image.close()
        return texture_l, texture_r

    def OnCreateDevice(self):
        self.stereo_handle = c_void_p()
        NvAPI.Stereo_CreateHandleFromIUnknown(self.device, byref(self.stereo_handle))

        # Load both images from the MPO file into a pair of textures:
        self.texture_l, self.texture_r = self.load_stereo_mpo(self.filename)

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
        a = float(self.image.width) / self.image.height
        if a > res_a:
            self.scale = float(self.presentparams.BackBufferWidth) / self.image.width
        else:
            self.scale = float(self.presentparams.BackBufferHeight) / self.image.height
        self.pan = (0, 0)

    def OnInit(self):
        # FIXME: Enumerate the best resolution:
        self.fullscreenres = (1920, 1080)
        self.ToggleFullscreen()
        self.fit_to_window()

    def OnKey(self, (msg, wParam, lParam)):
        if msg == 0x100: # WM_KEYDOWN (Normal key)
            # Borrow some geeqie style key bindings, and some custom ones
            if wParam == ord('Z'):
                self.scale = 1.0
                self.pan = (0, 0)
            elif wParam == ord('X'):
                self.fit_to_window()
            elif wParam == ord('P'):
                self.mode = MODES.PARALLAX
            else:
                print("unhandled normal key: wParam: 0x%x" % wParam)
        elif msg == 0x101: # WM_KEYUP
            if wParam == ord('P'):
                self.mode = MODES.DEFAULT

    def OnMouse(self, (msg, x, y, wheel, modifiers)):
        if msg == 0x20a: # Mouse wheel
            self.scale = max(self.scale * (1.0 + wheel / 900.0), 0.025)
            print('scale: %f' % self.scale)
        elif msg == 0x200: # Mouse move
            if self.mouse_last is None:
                dx = 0
                dy = 0
            else:
                dx = x - self.mouse_last[0]
                dy = y - self.mouse_last[1]
            self.mouse_last = x, y
            if self.mode == MODES.DEFAULT:
                if modifiers & 0x0001: # Left button down - panning
                    self.pan = self.pan[0] + dx, self.pan[1] + dy
                    print('pan: %dx%d' % self.pan)
                if modifiers & 0x0010: # Middle button down - parallax adjustment
                    self.parallax += dy / self.scale / self.image.height * 100.0
                    print('parallax: %f' % self.parallax)
            elif self.mode == MODES.PARALLAX:
                if modifiers & 0x0001: # Left button down
                    self.parallax += dx / self.scale / self.image.width * 200.0
                    print('parallax: %f' % self.parallax)
                elif modifiers & 0x0002: # Right button down
                    self.parallax -= dx / self.scale / self.image.width * 200.0
                    print('parallax: %f' % self.parallax)
        else:
            print("unhandled mouse message: msg: 0x%x, x: %i, y: %i, wheel: %i" % (msg, x, y, wheel))

    def calc_rect(self, eye):

        x = eye / 2.0 * self.parallax / 100.0 * self.image.width
        y = 0

        w = self.image.width * self.scale
        h = self.image.height * self.scale
        x = x * self.scale + (self.presentparams.BackBufferWidth - w) / 2
        y = y * self.scale + (self.presentparams.BackBufferHeight - h) / 2

        x, y = x + self.pan[0], y + self.pan[1]

        return x, y, w, h

    def update_vertex_buffer_eye(self, vbuffer, eye):
        # Update the vertex buffer with the vertex positions and texture
        # coordinates that correspond to the current paralax and crop
        ptr = c_void_p()
        vbuffer.Lock(0, 0, byref(ptr), 0)

        x, y, w, h = self.calc_rect(eye)

        data = (Vertex * 4)(
            #        X    Y  Z  RHW  U  V
            Vertex(  x,   y, 1, 1.0, 0, 0),
            Vertex(x+w,   y, 1, 1.0, 1, 0),
            Vertex(  x, y+h, 1, 1.0, 0, 1),
            Vertex(x+w, y+h, 1, 1.0, 1, 1),
        )
        ctypes.memmove(ptr, data, sizeof(Vertex) * 4)
        vbuffer.Unlock()

    def OnUpdate(self):
        self.update_vertex_buffer_eye(self.vbuffer_l, -1)
        self.update_vertex_buffer_eye(self.vbuffer_r,  1)

    def OnRender(self):
        self.device.SetFVF(VERTEXFVF)

        NvAPI.Stereo_SetActiveEye(self.stereo_handle, STEREO_ACTIVE_EYE.LEFT)
        self.device.Clear(0, None, D3DCLEAR.TARGET | D3DCLEAR.ZBUFFER, 0xff000000, 1.0, 0)
        self.device.SetStreamSource(0, self.vbuffer_l, 0, sizeof(Vertex))
        self.device.SetTexture(0, self.texture_l)
        self.device.DrawPrimitive(D3DPT.TRIANGLESTRIP, 0, 2)

        NvAPI.Stereo_SetActiveEye(self.stereo_handle, STEREO_ACTIVE_EYE.RIGHT)
        self.device.Clear(0, None, D3DCLEAR.TARGET | D3DCLEAR.ZBUFFER, 0xff000000, 1.0, 0)
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

    raise NotImplementedError()

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
    NvAPI.Initialize()
    NvAPI.Stereo_SetDriverMode(STEREO_DRIVER_MODE.DIRECT)

    try:
        filename = sys.argv[1]
    except IndexError:
        print('usage: %s filename.mpo' % (sys.argv[0]))
        return
    f = CropTool(filename, "Stereo Photo Cropping Tool")
    f.Mainloop()

    NvAPI.Unload()

if __name__ == '__main__':
    main()

# vi:et:sw=4:ts=4
