Stereo Photo Cropping Tool
==========================

The Stereo Photo Cropping Tool allows stereo photos to be edited with a live
preview to adjust the stereo parallax and crop the images quickly and
accurately. Unlike other tools, it also allows the depth of the crop lines to
be adjusted to create a more comfortable stereo image. It achieves this by
adding borders in the resulting image file where necessary to ensure the
correct placement of the stereo images. The border colour will match the
background when viewing the image in the program, and can by cycled through a
few presets with B.

It supports NVIDIA 3D Vision Direct, Side-by-Side and Top-and-Bottom output
formats. It can open .mpo files produced by most 3D cameras, as well as side by
side .jps files. Images are saved in the .jps format upon closing.

Starting from version 1.1, the program saves a .spct file next to the modified
.jps file, which opens the original file with the same adjustments pre-applied.
This prevents loss of quality from successive cropping sessions, allows photos
to be uncropped without having to start from scratch, and facilitates
re-applying a crop to an image where the source has since been modified (e.g.
by rawtherapee).

If you find this program useful, consider supporting me on [Patreon][1]

[1]: https://www.patreon.com/DarkStarSword

Controls
--------
- Left button + drag: Pan image
- Mouse wheel: Zoom image
- Z: Zoom to 100%
- X: Zoom to fit window
- Middle button + drag up/down: Adjust stereo parallax
- Control + left button + drag border: Adjust crop left/right/up/down
- Control + right button + drag border: Adjust crop backwards/forwards
- Escape: Save image (if modified) to a new file and exit
- Page Up: Save image (if modified) to a new file and load previous file in directory
- Page Down: Save image (if modified) to a new file and load next file in directory
- Shift + Mouse wheel: Save image (if modified) and load the previous / next file
- S: Immediately save image to a new file
- B: Cycle background colour (will be saved into image)
- O: Cycle output formats (3D Vision, Side-by-Side, Top-and-Bottom)
- I: Swap eyes (will not affect output image)
- F: Toggle full screen
- V + left/right button + drag up/down: Adjust vertical alignment (use the mouse cursor as a guide)

Known Limitations
-----------------
- The parallax embedded in the .mpo files is currently ignored (due to library
  limitations), however the tool makes it trivial to correct the parallax in
  mere seconds so this should only be a minor issue.
