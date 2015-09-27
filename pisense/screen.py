from __future__ import (
    unicode_literals,
    absolute_import,
    print_function,
    division,
    )
str = type('')

import io
import os
import glob
import mmap
import errno

import RTIMU
import numpy as np

from .common import color_dtype
from .font import SenseFont


class SensePixels(np.ndarray):
    def __new__(cls):
        result = np.ndarray.__new__(cls, shape=(8, 8), dtype=color_dtype)
        result._screen = None
        return result

    def __array_finalize__(self, obj):
        if obj is None:
            return
        self._screen = getattr(obj, '_screen', None)

    def __setitem__(self, index, value):
        super(SensePixels, self).__setitem__(index, value)
        if self._screen:
            # If we're a slice of the original pixels value, find the parent
            # that contains the complete array and send that to _set_pixels
            a = self
            while a.shape != (8, 8) and a.base is not None:
                a = a.base
            self._screen._set_pixels(a)

    def __setslice__(self, i, j, sequence):
        super(SensePixels, self).__setslice__(i, j, sequence)
        if self._screen:
            a = self
            while a.shape != (8, 8) and a.base is not None:
                a = a.base
            self._screen._set_pixels(a)


class SenseScreen(object):
    SENSE_HAT_FB_NAME = 'RPi-Sense FB'

    def __init__(self):
        self._fb_file = io.open(self._fb_device(), 'wb+')
        self._fb_mmap = mmap.mmap(self._fb_file.fileno(), 128)
        self._fb_array = np.frombuffer(self._fb_mmap, dtype=np.uint16).reshape((8, 8))
        self._fonts = {}
        self._hflip = False
        self._vflip = False
        self._rotate = 0

    def close(self):
        self._fb_array = None
        self._fb_mmap.close()
        self._fb_file.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, exc_tb):
        self.close()

    def _fb_device(self):
        for device in glob.glob('/sys/class/graphics/fb*'):
            try:
                with io.open(os.path.join(device, 'name'), 'r') as f:
                    if f.read().strip() == self.SENSE_HAT_FB_NAME:
                        return os.path.join('/dev', os.path.basename(device))
            except IOError as e:
                if e.errno != errno.ENOENT:
                    raise
        raise RuntimeError('unable to locate SenseHAT framebuffer device')

    def _get_raw(self):
        return self._fb_array
    def _set_raw(self, value):
        self._fb_array[:] = value
    raw = property(_get_raw, _set_raw)

    def _get_pixels(self):
        result = SensePixels()
        result['red']   = ((self.raw & 0xF800) >> 8).astype(np.uint8)
        result['green'] = ((self.raw & 0x07E0) >> 3).astype(np.uint8)
        result['blue']  = ((self.raw & 0x001F) << 3).astype(np.uint8)
        # Fill the bottom bits
        result['red']   |= result['red']   >> 5
        result['green'] |= result['green'] >> 6
        result['blue']  |= result['blue']  >> 5
        # Undo rotations and flips
        result = np.rot90(result, (360 - self._rotate) // 90)
        if self._hflip:
            result = np.fliplr(result)
        if self._vflip:
            result = np.flipud(result)
        # Activate callbacks on modification by giving the array a reference
        # to ourselves
        result._screen = self
        return result
    def _set_pixels(self, value):
        if isinstance(value, np.ndarray):
            value = value.view(color_dtype).reshape((8, 8))
        else:
            value = np.array(value, dtype=color_dtype).reshape((8, 8))
        if self._vflip:
            value = np.flipud(value)
        if self._hflip:
            value = np.fliplr(value)
        value = np.rot90(value, self._rotate // 90)
        self.raw = (
                ((value['red']   & 0xF8).astype(np.uint16) << 8) |
                ((value['green'] & 0xFC).astype(np.uint16) << 3) |
                ((value['blue']  & 0xF8).astype(np.uint16) >> 3)
                )
    pixels = property(_get_pixels, _set_pixels)

    def _get_vflip(self):
        return self._vflip
    def _set_vflip(self, value):
        p = self.pixels
        self._vflip = bool(value)
        self.pixels = p
    vflip = property(_get_vflip, _set_vflip)

    def _get_hflip(self):
        return self._hflip
    def _set_hflip(self, value):
        p = self.pixels
        self._hflip = bool(value)
        self.pixels = p
    hflip = property(_get_hflip, _set_hflip)

    def _get_rotate(self):
        return self._rotate
    def _set_rotate(self, value):
        if value not in (0, 90, 180, 270):
            raise ValueError('rotate must be 0, 90, 180, or 270')
        p = self.pixels
        self._rotate = value
        self.pixels = p
    rotate = property(_get_rotate, _set_rotate)

    def clear(self):
        self.raw = 0

    def draw(self, image):
        if not isinstance(image, np.ndarray):
            try:
                buf = image.tobytes()
            except AttributeError:
                try:
                    buf = image.tostring()
                except AttributeError:
                    raise ValueError('image must be an 8x8 PIL image or numpy array')
            image = np.frombuffer(buf, dtype=np.uint8)
            if len(image) == 192:
                image = image.reshape((8, 8, 3))
            elif len(image) == 64:
                image = image.reshape((8, 8))
                image = np.dstack((image, image, image))
            else:
                raise ValueError('image must be 8x8 pixels in size')
        self.pixels = image

    def marquee(
            self, text, font=None, foreground=(255, 255, 255),
            background=(0, 0, 0), letter_space=1):
        if font is None:
            # XXX Replace this with pkg_resources.resource_stream
            font = SenseFont(os.path.join(os.path.dirname(__file__), 'small.dat'))
        image = font.render_line(text, foreground, background, letter_space)
        for x in range(image.shape[1] - 8):
            self.pixels = image[:8, x:x + 8]
            time.sleep(0.1)

