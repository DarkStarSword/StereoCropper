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
import ctypes, struct, math, itertools, re, json
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

nv3d = True

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
        ('u', c_float),
        ('v', c_float),
    ]

VERTEXFVF = D3DFVF.XYZ | D3DFVF.TEX2

class MODES:
    DEFAULT = 0
    PARALLAX = 1
    CROP = 2
    CROP_LEFT = 3
    CROP_RIGHT = 4
    CROP_TOP = 5
    CROP_BOTTOM = 6
    VERTICAL_ALIGNMENT = 7
    hold_keys = {
            ord('P'): PARALLAX,
            ord('C'): CROP,
            0x11: CROP, # VK_CONTROL
            ord('V'): VERTICAL_ALIGNMENT,
    }

class OUTPUT_FORMAT:
    NV3D = 0
    SBSFH = 1
    SBSHH = 2
    TABFW = 3
    TABHW = 4
    MONO  = 5
    NUM = MONO + 1

    viewports = {
        #          Left eye                    Right eye
        SBSFH: [[0.0 , 0.0 , 0.5, 1.0], [0.5 , 0.0 , 0.5, 1.0]],
        SBSHH: [[0.0 , 0.25, 0.5, 0.5], [0.5 , 0.25, 0.5, 0.5]],
        TABFW: [[0.0 , 0.0 , 1.0, 0.5], [0.0 , 0.5 , 1.0, 0.5]],
        TABHW: [[0.25, 0.0 , 0.5, 0.5], [0.25, 0.5 , 0.5, 0.5]],
        MONO:  [[0.0 , 0.0 , 1.0, 1.0], [0.0 , 0.0 , 0.0, 0.0]],
    }

    @classmethod
    def set_viewport(cls, viewport, format, eye_idx, width, height):
        if format not in cls.viewports:
            viewport.X = 0
            viewport.Y = 0
            viewport.Width = width
            viewport.Height = height
            return

        vp = cls.viewports[format][eye_idx]
        viewport.X = int(vp[0] * width)
        viewport.Y = int(vp[1] * height)
        viewport.Width = int(vp[2] * width)
        viewport.Height = int(vp[3] * height)

    @classmethod
    def translate_mouse(cls, format, x, y, width, height):
        if format not in cls.viewports:
            return x, y
        vp = cls.viewports[format]
        x = (float(x) / width - vp[0][0]) / vp[0][2]
        y = (float(y) / height - vp[0][1]) / vp[0][3]
        if format in (cls.SBSFH, cls.SBSHH) and x >= 1.0: x -= 1.0
        if format in (cls.TABFW, cls.TABHW) and y >= 1.0: y -= 1.0
        return int(x * width), int(y * height)

    @classmethod
    def scale_mouse(cls, format, dx, dy):
        if format not in cls.viewports:
            return dx, dy
        vp = cls.viewports[format]
        return dx / vp[0][2], dy / vp[0][3]

ImageRect = namedtuple('ImageRect', ['x', 'y', 'w', 'h', 'u1', 'v1', 'u2', 'v2'])

def saturate(n):
    return min(max(n, 0.0), 1.0)

# The Frame class from the util module is not an ideal fit for my needs, but it
# will work and will save time so I'll use it for now.
class CropTool(Frame):
    def __init__(self, filename, *a, **kw):
        self.reinit(filename)
        self.background = backgrounds[0]
        self.output_format = OUTPUT_FORMAT.NV3D
        self.check_output_format()
        self.swap_eyes = False
        return Frame.__init__(self, *a, **kw)

    def reinit(self, filename):
        self.filename = filename
        self.scale = 1.0
        self.mouse_last = None
        self.mode = MODES.DEFAULT
        self.pan = (0.0, 0.0)
        self.parallax = 0.0
        self.vertical_alignment = 0.0
        self.vcrop = [0.0, 1.0]
        self.hcrop = [[0.0, 1.0], [0.0, 1.0]]
        self.dirty = False

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

    def is_stereo_image_extension(self):
        return os.path.splitext(self.filename)[1].lower() in ('.jps', '.pns')

    def get_image_eye(self, eye):
        if not self.is_stereo_image_extension():
            self.image_height = self.image.height
            self.image_width = self.image.width
            return self.image

        self.image_height = self.image.height
        if self.image.format == 'MPO':
            self.image.seek(eye == 1)
            self.image_width = self.image.width
            return self.image
        elif self.image.format in ('JPEG', 'PNG'):
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

    def load_spct(self, filename):
        spct_json = json.load(open(filename, 'r'))
        if spct_json['file_version'] != '1.0':
            print('Unsupported file version %s' % spct_json.file_version)
            self.Quit()
        self.filename = os.path.join(os.path.dirname(filename), spct_json['filename'])
        self.parallax = spct_json['parallax']
        self.vertical_alignment = spct_json['vertical_alignment']
        self.vcrop = spct_json['vertical_crop']
        self.hcrop = spct_json['horizontal_crop']
        self.background = spct_json['background']

    def load_image(self):
        if os.path.splitext(self.filename)[1].lower() == '.spct':
            self.load_spct(self.filename)

        # Load both images from the MPO file into a pair of textures:
        self.texture = self.load_stereo_image(self.filename)

    def calc_horizontal_offsets(self):
        h_offset = [self.hcrop[0][0] - self.parallax / 200.0,
                    self.hcrop[1][0] + self.parallax / 200.0]

        # Align one of the two images to the left of the final image:
        if h_offset[0] < h_offset[1]:
            h_offset[1] -= h_offset[0]
            h_offset[0] = 0.0
        else:
            h_offset[0] -= h_offset[1]
            h_offset[1] = 0.0

        return h_offset

    def calc_final_image_width(self, horizontal_offsets):
        # Calculate the width taking cropping and parallax into account. The
        # width will be the maximum required for the two images, but no more -
        # one of the images should be aligned to the right.
        # FIXME: There is still a minor off by one error that might result in a
        # single black column on the right of an image that shouldn't be there,
        # depending on floating point rounding.
        return int(math.ceil(max(self.hcrop[0][1] - self.hcrop[0][0] + horizontal_offsets[0], self.hcrop[1][1] - self.hcrop[1][0] + horizontal_offsets[1]) * self.image_width))

    def save_adjusted_image(self):
        base_filename = os.path.join(os.path.dirname(self.filename), self.file_prefix(self.filename)) + '-cropped'
        extension = os.path.splitext(self.filename)[1]
        if extension.lower() == '.png':
            extension = '.pns'
        elif extension.lower() not in ('.jps', '.pns'):
            extension = '.jps'
        jpg_filename = base_filename + extension
        spct_filename = base_filename + '.spct'
        i = 0
        while os.path.exists(jpg_filename):
            i += 1
            jpg_filename = base_filename + '-%d%s' % (i, extension)
            spct_filename = base_filename + '-%d.spct' % i
        print('Saving %s + %s...' % (jpg_filename, spct_filename))

        spct_json = {
            'file_version': '1.0',
            'filename': os.path.basename(self.filename),
            'parallax': self.parallax,
            'vertical_alignment': self.vertical_alignment,
            'vertical_crop': self.vcrop,
            'horizontal_crop': self.hcrop,
            'background': self.background,
        }
        json.dump(spct_json, open(spct_filename, 'w'))

        h_offset = self.calc_horizontal_offsets()
        width = self.calc_final_image_width(h_offset)
        height = (self.vcrop[1] - self.vcrop[0] - abs(self.vertical_alignment)) * self.image_height

        byteswapped_background = struct.unpack('<I', struct.pack('>I', self.background))[0] >> 8
        new_img = Image.new(self.image.mode, (width * 2, int(round(height))), byteswapped_background)

        for eye_idx, eye_multiplier in ((0, -1.0), (1, 1.0)):
            # Vertical alignment
            adj = eye_multiplier * self.vertical_alignment
            adj1 = adj2 = 0
            if adj > 0:
                adj1 = adj
            else:
                adj2 = adj

            # Left image goes on the right:
            side_off = 0
            if eye_idx == 0:
                side_off = width

            image = self.get_image_eye(eye_idx)
            cropped = image.crop((
                self.hcrop[eye_idx][0] * image.width,
                (self.vcrop[0] + adj1) * image.height,
                self.hcrop[eye_idx][1] * image.width,
                (self.vcrop[1] + adj2) * image.height))
            new_img.paste(cropped, (side_off + int(round(h_offset[eye_idx] * image.width)), 0))
            cropped.close()

        new_img.save(jpg_filename, format='JPEG')
        new_img.close()
        self.dirty = False

    def OnCreateDevice(self):
        global nv3d
        self.stereo_handle = c_void_p()
        if nv3d:
            try:
                NvAPI.Stereo_CreateHandleFromIUnknown(self.device, byref(self.stereo_handle))
            except NvAPI_Exception as e:
                print('Unable to initialise 3D Vision: %s' % str(e))
                nv3d = False
                self.check_output_format()

        self.load_image()

        # Create two vertex buffers for the images in each eye. Later we might
        # switch to the programmable pipeline and work out the offsets in the
        # vertex shader instead, but for now this is easier
        self.vbuffer = [POINTER(IDirect3DVertexBuffer9)(), POINTER(IDirect3DVertexBuffer9)()]
        self.device.CreateVertexBuffer(sizeof(Vertex) * 4, 0, 0,
            D3DPOOL.MANAGED, byref(self.vbuffer[0]), None)
        self.device.CreateVertexBuffer(sizeof(Vertex) * 4, 0, 0,
            D3DPOOL.MANAGED, byref(self.vbuffer[1]), None)

    def OnDestroyDevice(self):
        del self.texture
        del self.vbuffer

    def load_new_file(self, filename):
        self.reinit(filename)
        self.load_image()
        self.fit_to_window()

    def fit_to_window_uncropped(self):
        res_a = float(self.presentparams.BackBufferWidth) / self.presentparams.BackBufferHeight
        a = float(self.image_width) / self.image_height
        if a > res_a:
            self.scale = float(self.presentparams.BackBufferWidth) / self.image_width
        else:
            self.scale = float(self.presentparams.BackBufferHeight) / self.image_height
        self.pan = (0.0, 0.0)

    def fit_to_window(self):
        res_a = float(self.presentparams.BackBufferWidth) / self.presentparams.BackBufferHeight
        # There are some edge cases where we need to take the parallax into
        # account, so we can't just use the previous frame's rectangle. e.g.
        # make the left image max width but shrink the right image on both left
        # and right, adjust parallax and fit to window.
        minc = min(self.hcrop[0][0], self.hcrop[1][0])
        maxc = max(self.hcrop[0][1], self.hcrop[1][1])

        # Changed to use the same width calculations as when saving an image to
        # fix scaling the image too small when cropped on both sides:
        h_offset = self.calc_horizontal_offsets()
        w = self.calc_final_image_width(h_offset)

        h = (self.vcrop[1] - self.vcrop[0] - abs(self.vertical_alignment)) * self.image_height
        a = w / h
        if a > res_a:
            self.scale = float(self.presentparams.BackBufferWidth) / w
        else:
            self.scale = float(self.presentparams.BackBufferHeight) / h

        # But we do use the crop values to calculate the new pan. Since this
        # will be centered the parallax and vertical adjustments can be
        # ignored:
        self.pan = ((1.0 - maxc - minc) * self.image_width * self.scale / 2.0,
                (1.0 - self.vcrop[1] - self.vcrop[0]) * self.image_height * self.scale / 2.0)

    def OnInit(self):
        self.ToggleFullscreen()
        self.fit_to_window_uncropped()

    def cycle_background_colours(self):
        self.background = backgrounds[(backgrounds.index(self.background) + 1) % len(backgrounds)]

    def check_output_format(self):
        if not nv3d and self.output_format == OUTPUT_FORMAT.NV3D:
            self.output_format += 1

    def cycle_output_formats(self):
        self.output_format = (self.output_format + 1) % OUTPUT_FORMAT.NUM
        self.check_output_format()

    file_prefix_pattern = re.compile(r'-cropped(?:-(?P<idx>[0-9]+))?')
    def file_prefix(self, filename):
        name = os.path.basename(filename).lower()
        name = os.path.splitext(name)[0]
        match = self.file_prefix_pattern.search(name)
        if match is not None:
            return name[:match.start()]
        return name

    def find_prev_next_file(self):
        def file_supported(filename):
            return os.path.splitext(filename)[1].lower() in ('.mpo', '.jps', '.spct', '.pns')

        dirname = os.path.dirname(os.path.join(os.curdir, self.filename))
        files = os.listdir(dirname)
        files = filter(file_supported, files)
        files = sorted(files, key=self.file_prefix)
        # Remember - don't convert the result of groupby to a list prematurely
        # or internal iterators will be useless:
        files = itertools.groupby(files, self.file_prefix)
        cur_group = self.file_prefix(self.filename)
        cur_idx = 0
        file_groups = []
        for i, (group, file_group) in enumerate(files):
            file_groups.append(list(file_group))
            if group == cur_group:
                cur_idx = i
        prev = file_groups[(cur_idx - 1) % len(file_groups)]
        next = file_groups[(cur_idx + 1) % len(file_groups)]
        prev = map(lambda x: os.path.join(dirname, x), prev)
        next = map(lambda x: os.path.join(dirname, x), next)
        return (prev, next)

    def highest_priority_file(self, files):
        def file_cmp(a, b):
            '''
            Comparison function to sort files so the highest priority will be
            first. Files must already have been reduced to a set of related files
            (same filename prefix) and that can be opened by this tool. Previously
            cropped files take priority over uncropped files, and .spct files
            will take priority over .jps, .pns or .mpo files.
            '''
            # Check for previously cropped files:
            match_a = self.file_prefix_pattern.search(a)
            match_b = self.file_prefix_pattern.search(b)
            if match_a is not None and match_b is None:
                return -1
            if match_a is None and match_b is not None:
                return 1
            if match_a is not None and match_b is not None:
                # Both files were previously cropped, the one with the highest
                # index takes priority:
                idx_a  = match_a.group('idx')
                idx_b  = match_b.group('idx')
                if idx_a is None and idx_b is not None:
                    return 1
                if idx_a is not None and idx_b is None:
                    return -1
                if idx_a is not None and idx_b is not None:
                    # Higher index takes priority, so reverse sort:
                    result = -cmp(int(idx_a), int(idx_b))
                    if result:
                        return result
                    # Index on both files is the same, continue with other
                    # comparisons

            # Prioritise .spct files over anything else:
            ext_a = os.path.splitext(a)[1].lower()
            ext_b = os.path.splitext(b)[1].lower()
            if ext_a == '.spct' and ext_b != '.spct':
                return -1
            if ext_a != '.spct' and ext_b == '.spct':
                return 1

            # No real policy from this point onwards, resort to alphabetical. We
            # could maybe prioritise .mpo over .jps, but it's not clear that would
            # always be the correct answer.
            return cmp(a, b)
        return sorted(files, cmp=file_cmp)[0]

    def open_prev_file(self):
        if self.dirty:
            self.save_adjusted_image()
        filename = self.highest_priority_file(self.find_prev_next_file()[0])
        print('Previous file: %s...' % filename)
        self.load_new_file(filename)

    def open_next_file(self):
        if self.dirty:
            self.save_adjusted_image()
        filename = self.highest_priority_file(self.find_prev_next_file()[1])
        print('Next file: %s...' % filename)
        self.load_new_file(filename)

    def OnKey(self, (msg, wParam, lParam)):
        if msg == 0x100 and not lParam & 0x40000000: # WM_KEYDOWN that is not a repeat
            # Borrow some geeqie style key bindings, and some custom ones
            if wParam == 0x1B: # Escape
                if self.dirty:
                    self.save_adjusted_image()
                self.Quit()
            elif wParam == ord('Z'):
                self.scale = 1.0
                self.pan = (0.0, 0.0)
            elif wParam == ord('X'):
                self.fit_to_window()
            elif wParam == ord('F'):
                self.ToggleFullscreen()
                self.fit_to_window()
            elif wParam == ord('S'):
                self.save_adjusted_image()
            elif wParam == ord('B'):
                self.cycle_background_colours()
            elif wParam == ord('O'):
                self.cycle_output_formats()
            elif wParam == ord('I'):
                self.swap_eyes = not self.swap_eyes
            elif wParam in MODES.hold_keys:
                self.mode = MODES.hold_keys[wParam]
            elif wParam == 0x21: # Page Up
                self.open_prev_file()
            elif wParam == 0x22: # Page Down
                self.open_next_file()
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
                x, y = OUTPUT_FORMAT.translate_mouse(self.output_format, x, y,
                        self.presentparams.BackBufferWidth, self.presentparams.BackBufferHeight)
                xa = (self.rect[0].x + self.rect[1].x) / 2.0
                wa = (self.rect[0].w + self.rect[1].w) / 2.0
                if wa <= 0: # Divide by zero protection
                    if x > xa:
                        self.mode = MODES.CROP_RIGHT
                    else:
                        self.mode = MODES.CROP_LEFT
                elif self.rect[0].h <= 0:
                    if y > self.rect[0].x:
                        self.mode = MODES.CROP_BOTTOM
                    else:
                        self.mode = MODES.CROP_TOP
                else:
                    xp = float(x - xa) / wa
                    yp = float(y - self.rect[0].y) / self.rect[0].h
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
            if modifiers & 0x0004: # Shift
                # If this was primarily a viewer I'd go for the wheel by itself
                # to select previous/next image and ctrl+wheel to zoom for
                # consistency with other good image viewers, but as it is
                # primarily aimed at editing we don't want to make it too easy
                # to change images accidentally given that ctrl+wheel needs to
                # be held for some of the manipulations. Don't want to violate
                # the meaning of ctrl+wheel up/down, so use shift+wheel instead.
                if wheel < 0:
                    self.open_next_file()
                else:
                    self.open_prev_file()
            else:
                x, y = OUTPUT_FORMAT.translate_mouse(self.output_format, x, y,
                        self.presentparams.BackBufferWidth, self.presentparams.BackBufferHeight)
                new_scale = max(self.scale * (1.0 + wheel / 900.0), 0.025)
                self.pan = ((self.pan[0] - x + self.presentparams.BackBufferWidth / 2.0) * new_scale / self.scale + x - self.presentparams.BackBufferWidth / 2.0,
                            (self.pan[1] - y + self.presentparams.BackBufferHeight / 2.0) * new_scale / self.scale + y - self.presentparams.BackBufferHeight / 2.0)
                self.scale = new_scale
        elif msg == 0x200: # Mouse move
            if self.mouse_last is None:
                dx = dy = dix = diy = 0
            else:
                dx, dy = OUTPUT_FORMAT.scale_mouse(self.output_format, x - self.mouse_last[0], y - self.mouse_last[1])
                dix = dx / self.scale / self.image_width
                diy = dy / self.scale / self.image_height
            self.mouse_last = x, y
            if self.mode == MODES.DEFAULT:
                if modifiers & 0x0001: # Left button down - panning
                    self.pan = self.pan[0] + dx, self.pan[1] + dy
                if modifiers & 0x0010: # Middle button down - parallax adjustment
                    self.parallax += dy / self.scale / self.image_height * 50.0
                    self.dirty = True
            elif self.mode == MODES.PARALLAX:
                if modifiers & 0x0001: # Left button down
                    self.parallax += dix * 200.0
                    self.dirty = True
                elif modifiers & 0x0002: # Right button down
                    self.parallax -= dix * 200.0
                    self.dirty = True
            elif self.mode == MODES.VERTICAL_ALIGNMENT:
                if modifiers & 0x0001: # Left button down
                    self.vertical_alignment += diy * 2.0
                    self.dirty = True
                elif modifiers & 0x0002: # Right button down
                    self.vertical_alignment -= diy * 2.0
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
                    self.hcrop[1][0] = min(saturate(self.hcrop[1][0] - diy / 4.0), self.hcrop[1][1])
                    self.hcrop[0][0] = min(saturate(self.hcrop[0][0] + diy / 4.0), self.hcrop[0][1])
                    self.dirty = True
            elif self.mode == MODES.CROP_RIGHT:
                if modifiers & 0x0001: # Left button down - crop left/right
                    self.hcrop[1][1] = max(saturate(self.hcrop[1][1] + dix), self.hcrop[1][0])
                    self.hcrop[0][1] = max(saturate(self.hcrop[0][1] + dix), self.hcrop[0][0])
                    self.dirty = True
                elif modifiers & 0x0002: # Right buttons down - move up/down to crop back/forward
                    self.hcrop[1][1] = max(saturate(self.hcrop[1][1] - diy / 4.0), self.hcrop[1][0])
                    self.hcrop[0][1] = max(saturate(self.hcrop[0][1] + diy / 4.0), self.hcrop[0][0])
                    self.dirty = True

    def calc_rect(self, eye):

        # Crop
        u1 = self.hcrop[eye == 1.0][0]
        u2 = self.hcrop[eye == 1.0][1]
        x = u1
        w = u2 - u1
        v1 = self.vcrop[0]
        v2 = self.vcrop[1]
        y = v1
        h = v2 - v1

        # Vertical alignment
        adj = eye * self.vertical_alignment
        if adj > 0:
            v1 += adj
        else:
            v2 += adj
        y += abs(adj / 2.0)
        h -= abs(adj)

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

        # Path of least resistance to switch to untranslated coordinates:
        def x(x):
            return x / self.presentparams.BackBufferWidth * 2.0 - 1.0
        def y(y):
            return y / self.presentparams.BackBufferHeight * 2.0 - 1.0

        data = (Vertex * 4)(
            #              X            Y     Z     U     V
            Vertex(x(r.x    ), -y(r.y    ), 1.0, r.u1, r.v1),
            Vertex(x(r.x+r.w), -y(r.y    ), 1.0, r.u2, r.v1),
            Vertex(x(r.x    ), -y(r.y+r.h), 1.0, r.u1, r.v2),
            Vertex(x(r.x+r.w), -y(r.y+r.h), 1.0, r.u2, r.v2),
        )
        ctypes.memmove(ptr, data, sizeof(Vertex) * 4)
        vbuffer.Unlock()

    def OnUpdate(self):
        self.rect = self.calc_rect(-1), self.calc_rect(1)
        self.update_vertex_buffer_eye(self.vbuffer[0], self.rect[0])
        self.update_vertex_buffer_eye(self.vbuffer[1], self.rect[1])

    def render_eye(self, eye_idx):
        self.device.SetStreamSource(0, self.vbuffer[eye_idx], 0, sizeof(Vertex))
        self.device.SetTexture(0, self.texture[eye_idx])
        self.device.DrawPrimitive(D3DPT.TRIANGLESTRIP, 0, 2)

    def render_3d_vision(self):
        for eye_idx, nveye in ((0, STEREO_ACTIVE_EYE.LEFT), (1, STEREO_ACTIVE_EYE.RIGHT)):
            NvAPI.Stereo_SetActiveEye(self.stereo_handle, nveye)
            self.device.Clear(0, None, D3DCLEAR.TARGET | D3DCLEAR.ZBUFFER, 0xff000000 | self.background, 1.0, 0)
            if self.swap_eyes:
                eye_idx = 1 - eye_idx
            self.render_eye(eye_idx)

    def render_sbs(self):
        if nv3d:
            NvAPI.Stereo_SetActiveEye(self.stereo_handle, STEREO_ACTIVE_EYE.MONO)

        self.device.Clear(0, None, D3DCLEAR.TARGET | D3DCLEAR.ZBUFFER, 0xff000000 | self.background, 1.0, 0)

        viewport = D3DVIEWPORT9()
        viewport.MinZ = 0
        viewport.MaxZ = 1

        for eye in (0, 1):
            eye1 = eye
            if self.swap_eyes:
                eye1 = 1 - eye
            OUTPUT_FORMAT.set_viewport(viewport, self.output_format, eye1,
                    self.presentparams.BackBufferWidth, self.presentparams.BackBufferHeight)
            self.device.SetViewport(byref(viewport))
            self.render_eye(eye)

        # Set a fullscreen viewport before leaving, for the clear() in the next
        # frame and in case we switch to 3D Vision where we no longer set the
        # viewport
        viewport.X = 0
        viewport.Y = 0
        viewport.Width = self.presentparams.BackBufferWidth
        viewport.Height = self.presentparams.BackBufferHeight
        self.device.SetViewport(byref(viewport))

    def OnRender(self):
        self.device.SetRenderState(D3DRS.LIGHTING, False)
        self.device.SetFVF(VERTEXFVF)
        if self.output_format == OUTPUT_FORMAT.NV3D:
            self.render_3d_vision()
        else:
            self.render_sbs()

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
    global nv3d
    try:
        filename = sys.argv[1]
    except IndexError:
        root = Tkinter.Tk()
        root.withdraw()
        filename = tkFileDialog.askopenfilename(filetypes = [
            ('Stereo Images', ('.mpo', '.jps', '.pns', '.spct')),
            ('Mono Images', ('.jpg', '.jpeg', '.png')),
            ('Stereo Photo Cropping Tool files', '.spct'),
            ('MPO stereo images', '.mpo'),
            ('JPS stereo images', '.jps'),
            ('PNS stereo images', '.pns'),
            ('JPEG mono images', ('.jpg', '.jpeg')),
            ('PNG mono images', '.png'),
            ('All files', '*')
            ])
        if not filename:
            return

    try:
        NvAPI.Initialize()
    except NvAPI_Exception:
        nv3d = False
    else:
        enable_stereo_in_windowed_mode()
        NvAPI.Stereo_SetDriverMode(STEREO_DRIVER_MODE.DIRECT)

    f = CropTool(filename, "Stereo Photo Cropping Tool")
    f.Mainloop()

    if nv3d:
        NvAPI.Unload()

if __name__ == '__main__':
    main()

# vi:et:sw=4:ts=4
