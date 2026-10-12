# User Guide

This contains typical usage examples and workflow for users using this plugin.

---

## Prepping new design files


### Adding Print and Cut Layers

You are recommended to add a layer named `Print` and `Cut`.
The `Print` layer in addition to `Regmarks` will be ignored by `Send to Silhouette` extention.


### Add registration mark

<img src="./assets/screenshot_of_the_regmarked_document.png" alt="screenshot of the regmarked document" height=200px>

The plotter will search the registration marks at the given positions.
If it locates the marks, they will serve as accurate reference and define the origin.
Therefore it is necessary to set the correct offset values of the mark.
As a result the cut will go precisely along the graphics.

1. Extention > Render > Silhouette Regmarks
1. For a Cameo 5 Alpha, select **4 corner (four L-marks, e.g. Cameo 5 Alpha)** as the registration mark style
1. Check regmark from document left and top is set to desired value
1. Set mark to mark distance or clear it to zero if autocalculating from document size
1. Press Apply

This will create a new layer called `Regmarks` with the newly generated registration mark. In a multi-page document, it creates one `Regmarks (page N)` layer on every page.

On the bottom will also be a string shown below that would remind you what settings this was generated with.
- `mark distance from document: Left=10.0mm, Top=10.0mm; mark to mark distance: X=190.0mm, Y=277.0mm;`

Note: You have the option of using the provided template at `examples/registration-marks-cameo-silhouette-a4-maxi.svg` for Silhouette Cameo using A4 paper format. Cameo 5 Alpha users can use the ready-made A4 template at `templates/silhouette-cameo-5-alpha-registration-marks-a4.svg` without running the regmark generator.


---

## Print & cut sheets (stickers, temporary tattoos)

These extensions automate a print & cut sheet from a single design, for example a customer's logo:

**Silhouette Sheet Layout** (includes the solid black conversion) &rarr; **Silhouette Regmarks** &rarr; **Silhouette Cut Contour** &rarr; **Send to Silhouette**

**Silhouette Solid Black** can also be used on its own.

### Convert artwork to solid black

`Extensions > Render > Silhouette Solid Black`

For single-colour printing (for example temporary tattoos, which are printed in black only).

1. Select the artwork: vectors in any colour, gradients and bitmaps.
1. Choose the **Method**:
  - **Automatic**: if every colour is darker than the threshold, the vectors are simply recoloured black, which is exact. Otherwise the artwork is traced (below).
  - **Always trace**: the artwork is rendered as it looks (paint order, fills, strokes, opacity, bitmaps; a gradient counts as its average colour). Every point darker than the threshold becomes black and every lighter point (white, light colours) becomes no ink. The result is traced into one black path. White details lying on top of dark areas therefore become holes, which recolouring alone would lose.
  - **Only recolour the vectors black**: keeps the vectors and paints every fill and stroke black.
1. **Darkness from which a colour becomes black** (0–1, default 0.5): lower it to keep lighter colours, such as yellow, as black.
1. Press Apply.

Doubtful results are reported with a `CHECK:` message:
- more than 15% of the coloured artwork was too light and dropped;
- more than 30% of the colour boundaries were lost, because areas told apart only by their colour became one black area;
- the result is more than 85% black, for example a coloured background that became a block.

Clip paths, masks and filters are not taken into account. Convert text to paths first.

### Lay out copies of a design on the sheet

`Extensions > Render > Silhouette Sheet Layout`

1. Import the design (SVG, PDF, PNG or JPG) and select it. If it is made of several objects, select them all; they are treated as one design.
1. On the **Design** tab:
  - **Tattoo size** and **Size applies to**: the final size of one copy (width, height or longest side). The proportions are kept.
  - **Number of copies**: how many copies you want. `0` fills the sheet.
  - **Mirror**: on by default, for temporary tattoo transfer paper. Untick it for stickers.
  - **Convert to solid black**: on by default (**Automatic**). Converts the design to solid black, exactly like **Silhouette Solid Black**, at the final size. Choose **Off** to keep colours and bitmaps as they are.
  - **Darkness from which a colour becomes black**: lower it to keep lighter colours as black.
1. On the **Packing** tab:
  - **Minimum distance between copies**: the space left between the artwork of two neighbouring copies.
  - **Cut line distance from the artwork**: should match the distance used later in **Silhouette Cut Contour**. The cut line is also kept inside the usable area.
  - **Allow turning the design 90°** and **Allow every other row / column turned 180°**: every other row or column turned upside down lets irregular shapes interlock, which usually fits more copies.
  - **Keep each design in one piece**: on by default. A design made of separate parts (for example a symbol and a word) is treated as one piece, so copies never slip between the parts of another copy.
1. On the **Usable area** tab, choose **Inside the registration marks** (print & cut) or **Page with a margin**. If the document already has marks drawn by **Silhouette Regmarks**, their position is read from the document; otherwise the values on this tab are used. The square zone around each corner mark (mark length + clearance) is kept free.
1. Press Apply.

The extension tries the design upright and turned 90°, in rows and in columns, all the same way up or alternating, and keeps the arrangement that fits the most copies. The selected design is moved into a master stored in the document definitions, and the copies are placed as clones in the `Print` layer: editing the master updates every copy. Running the extension again replaces the previous layout in that layer.

A message reports how many copies were placed and how many fit at that size, plus any `CHECK:` messages from the black conversion. If you ask for more copies than fit, it places those that fit and tells you the largest size at which all of them would fit, for example `For 8 copies the size must be at most 81.3 mm.`

Notes:
- Text must be converted to paths first (`Path > Object to Path`).
- PNG images always work. JPG and other bitmap formats need the Pillow library in the Python used by Inkscape.
- White counts as "no ink": transfer paper does not print white, so white areas are not treated as part of the design.

### Generate the cut contour

`Extensions > Render > Silhouette Cut Contour`

Creates a closed cut line around every design, at a set distance from the ink. Holes inside a design are not cut, giving a sticker-style outer cut. It works with vectors, bitmaps and the clones made by **Silhouette Sheet Layout**.

1. Select the designs to outline, or select nothing to outline everything in the visible layers.
1. On the **Settings** tab:
  - **Distance from artwork to cut line**: for example `1.5` mm.
  - **What is one design**:
    - **Each object / group**: every top-level object or group is one design. Group the parts of a design (`Ctrl+G`) first.
    - **Automatic: separate by empty space**: for a sheet that is a single path. Ink closer than **join parts closer than** is one design, and small parts inside a bigger design (text inside a frame, details) stay with it.
  - **Keep each design in one piece**: on by default. A design made of separate parts gets one contour around all of them, bridging gaps up to **Largest gap bridged inside a design**.
  - **Merge neighbouring cuts into a single line**: on by default. Two neighbours share one dividing line and the blade passes once instead of twice. Cut lines closer than **Merge cut lines closer than** become one line.
  - **Without merging: minimum distance between neighbouring cuts**: only used when merging is off.
  - **Add '(print)' to the artwork layer names**: on by default, so that **Send to Silhouette** does not cut the artwork itself.
1. Press Apply.

The contours are drawn in red in a `Cut contour` layer. Designs that are closer to each other than twice the distance share the space between them, so the cut lines never cross. With merging on, the first design gets a closed contour and its neighbours get open paths that end on the line already cut. Running the extension again replaces the previous contours.

Advanced settings: **Precision** (pixels per mm), **Simplification tolerance**, **Ignore contours smaller than** (drops specks) and the contour colour.

### Complete workflow

1. **Silhouette Sheet Layout**: solid black conversion, size, number of copies, mirror.
1. **Silhouette Regmarks**: draw the registration marks (see [Add registration mark](#add-registration-mark)). Use the same mark position as on the **Usable area** tab of the layout.
1. **Silhouette Cut Contour**: generate the cut lines.
1. Print the sheet with the `Print` and `Regmarks` layers visible and the `Cut contour` layer hidden.
1. **Send to Silhouette** with registration marks (see [Plot with registration marks steps](#plot-with-registration-marks-steps)). Layers whose names contain `Print` or `Regmarks` are ignored, so only the contours are cut.

Note: with registration marks the cutter only cuts inside the rectangle formed by the marks, so artwork and cut lines must stay inside it. The layout extension takes this into account.


---

## Plot

<img src="./assets/screenshot_of_send_to_silhouette.png" alt="screenshot of Send to Silhouette" height=200px>

1. Open your document with inkscape.
  - Note: documents in px are plotted at 96dpi
2. Convert text objects to paths (Path - Convert object to path)
3. Select the parts you want to plot.
4. Open the extension. If you want to use the same cut settings for all of the paths in your file, use "Extensions -> Export -> Send to Silhouette." If you want use different cut settings based on the colors of different items in your file, use "Extensions -> Export -> Silhouette Multi Action."
5. In the case of Multi Action, there is a first screen that is primarily for debugging. Typically you can just leave all of the boxes on this unchecked and click "Apply."
6. Set your desired plot parameters. There are numerous aspects you can control with the dialog, here are just the core highlights:
  - **X-Offset, Y-Offset**  An additional offset of your drawing from the top left corner. Default is 0/0
  - **Tool Cut/Pen**        Cut mode drews small circles for orientation of the blade, Pen mode draws exactly as given.
  - **Media**               Select a predfined media or set to custom settings.
  - **Speed**               Custom speed of the movements
  - **Pressure**            Custom Pressure on the blade. One unit is said to be 7g force.
  - Note: In Multi Action, you can select the color you want settings to apply to and then set all the same parameters, but with potentially different settings for each color. You can also change the order in which the colors are cut, and uncheck the box in the "Perform Action?" column to ignore a color altogether.
7. To start the cut, in "Send to Silhouette, click the "Apply" button; in "Silhouette Multi" click the "Execute" button.

Note: while Send to Silhouette runs, a small "Send to Silhouette" progress window shows the current step (reading the document, optimizing paths, connecting, sending) and, while the job is sent, the percentage sent. It closes before the preview opens and comes back when you click Cut. Inkscape's own "working, please wait" dialog stays open until the job ends. The progress window needs Python's `tkinter`; if `tkinter` is not available, the job runs without it.


### Plot with registration marks steps

<img src="./assets/screenshot_of_registration_mark_settings_page.png" alt="screenshot of registration mark settings page" height=200px>

1. Open the document which fit to your setup (e.g. With rendered registration mark as illustrated above)
2. Insert your cutting paths and graphics on the apropriate layers.
3. Printout the whole document including registration marks. You probably want to hide the cutting layer.
4. Select your cutting paths in the document, but exclude regmarks and graphics.
  - The extention is smart enough to ignore any layers that has the word `Print` or `Regmarks` in it.
5. On the **Regmarks** tab:
  - Check **Document has registration marks**
  - Check **Search for registration marks**
  - On a Cameo 5 Alpha, also check **Use 4 registration marks**
6. Set all following parameters according to the registration file used:
  - **X mark distance** (e.g. *190*)
  - **Y mark distance** (e.g. *277*)
  - **Position of regmark from document left** (e.g. *10*)
  - **Position of regmark from document top** (e.g. *10*)
  - Note: values are read from regmarks layer if 0 is entered
7. Set desired plot parameters as usual. Already explained in previous section.
8. Start cut.

On some devices have an offset between the search optics and the cutting knife.
For enhanced precision, you may have to set an offset on **X-Offset** and/or **Y-Offset** on the **Silhouette** tab to compensate.


### When the cutter does not find the marks

**Portrait 3 settings that work** (3 out of 3 detections, matching Silhouette Studio's defaults): marks **15.88 mm** from the page edges, 20 mm long, 0.5 mm thick (the Silhouette Regmarks defaults), and in Send to Silhouette the mark position and distances at **0** (read from the Regmarks layer) with **Start the search this many mm before the marks = 5.9**. With marks 10 mm from the edges the Portrait 3 answered `-1` (search refused) almost every time.

Some cutters (notably the Portrait 3) find registration marks only unreliably. Things that help, in this order:

1. **Search start.** On the **Regmarks** tab of Send to Silhouette, **Start the search this many mm before the marks** defaults to 10. Portrait cutters need **0**: they expect the actual mark position.
2. **Right-hand marks within reach.** The Portrait only cuts about 203 mm across: use an **X mark to mark distance** of about 180 mm in Silhouette Regmarks. The log warns when the marks are too far out.
3. **Bolder marks.** In **Silhouette Regmarks**, set **Mark length** (e.g. 25 mm) and **Mark line thickness** (e.g. 1 mm). Both are written into the Regmarks layer; Send to Silhouette reads them and tells the cutter (leave **Mark length / thickness** at 0 there).
4. **Automatic retries.** If the cutter reports the marks as not found, Send to Silhouette searches again with the expected position shifted by **Shift between search attempts** (default 1.5 mm), up to **If not found, search again this many times** (default 4). Each attempt is listed in the log.
5. **Physical conditions.** Clean the optical sensor (under the tool carriage), shade the cutter from strong light, print the marks solid black at best quality, and keep glossy media away from the marks (or cover the marks with matte tape).

To measure how reliable detection is without cutting anything, print `assets/folha_teste_marks.svg` once (100 %, black), load it like a normal Print & Cut sheet, open it in Inkscape and run Send to Silhouette with registration marks and search on, and **Test only: search the marks this many times without cutting** set to e.g. 10. The cutter searches the marks that many times at the expected position, parks the head, and reports e.g. `Registration mark test: found 7 of 10 (70%). Answers: '-1' x1, '0' x7, '1' x2. Search time 3.1-9.8 s.` Change one thing per round (light, sensor cleaning, mark position, reloading the sheet, the thickness told to the cutter) and compare the counts.

If the sensor still cannot be relied on, cut without marks:

1. `Extensions > Render > Silhouette Calibration Sheet` (for a Portrait 3 set **Keep targets within this width** to 195 mm).
1. Print it at 100% with the `Calibration cut` layer hidden, and put the sheet exactly in the top-left corner of the mat grid.
1. Send to Silhouette with registration marks **off** and X/Y-Offset 0.
1. At each target read where the cut crosses the two scales (+ = cut right of / below the print). Enter **minus the average reading** as **X-Offset** and **Y-Offset** on the main tab of Send to Silhouette.
1. For production, lay out with **Usable area: Page with a margin** in Silhouette Sheet Layout, skip the registration marks, place each sheet in the mat corner and cut with registration marks off. Expect about ±0.5–1 mm, depending on how squarely the sheet is placed; a cut distance of 1.5–2 mm keeps the blade off the ink.

---

## Connecting over Bluetooth

Bluetooth-capable cutters (Cameo 3 and newer, Portrait 2 and newer, Curio 2, and similar) can be driven wirelessly instead of over USB. The extension supports Bluetooth Classic and Bluetooth Low Energy as separate connection types.

### Bluetooth Classic (RFCOMM)

Bluetooth Classic is supported on Linux and Windows. Pair the cutter in the operating system's Bluetooth settings first, then make sure it is powered on and in range.

1. Open **Extensions &rarr; Export &rarr; Send to Silhouette** and switch to the **Bluetooth** tab.
2. Select **Bluetooth Classic (RFCOMM)** as the connection type.
3. Tick **Scan for nearby devices (list, then stop)** and click **Apply**. The extension lists visible devices and stops without plotting. For example:

   ```
   Found 1 Bluetooth Classic device(s):
       00:1B:41:33:44:55   CAMEO 5 ALPHA-000000

   Copy the address of the cutter you want into the 'Bluetooth MAC address' field.
   ```
4. Copy the address into **Bluetooth MAC address** and untick the scan option.
5. Set the plot parameters and click **Apply**.

On Linux the scan uses `bluetoothctl` (BlueZ). Installing PyBluez (`python3 -m pip install pybluez`) additionally enables a live inquiry.

### Bluetooth Low Energy (BLE)

BLE is supported through the optional `bleak` package. The macOS installer installs it automatically; on other systems install it into the Python environment used by Inkscape:

```sh
python3 -m pip install bleak
```

BLE does not require Bluetooth Classic pairing. Make sure Bluetooth is enabled and the cutter is powered on and in range.

1. Open **Extensions &rarr; Export &rarr; Send to Silhouette** and switch to the **Bluetooth** tab.
2. Select **Bluetooth Low Energy (BLE)**. On the first scan, macOS may ask for Bluetooth permission for Inkscape; allow it.
3. Tick **Scan for nearby devices (list, then stop)** and click **Apply**. Scanning intentionally lists every visible BLE device, not only Silhouette cutters.
4. Identify the cutter by its advertised name. The **BLE advertised name** field defaults to `CAMEO`; enter the exact name if more than one device matches.
5. Alternatively, copy the reported **BLE local identifier**. On macOS this is a computer-specific CoreBluetooth UUID, not a portable MAC address.
6. Untick the scan option, set the plot parameters, and click **Apply**.

The extension rejects ambiguous matches rather than choosing an arbitrary nearby device. It detects the cutter model from the firmware after connecting; use **Override cutter model** on the **Log and Dump** tab if the model is not recognised.

The complete Inkscape-to-cutter BLE flow has been verified with Inkscape 1.4.4 on macOS and a Silhouette Cameo 5 Alpha using the pen attachment, including discovery, connection, status checking, setup, and drawing.

### Media check

Before setup or plot commands are sent, the extension queries the cutter status. If no media is loaded—or the status cannot be confirmed—the job exits early, closes the connection, and displays an error. Load the media and run the job again.

### Command-line examples

```sh
# List visible Bluetooth Classic devices, then stop.
sendto_silhouette.py --connection_type=bluetooth --bluetooth_scan=True yourfile.svg

# Plot over Bluetooth Classic using an explicit MAC address.
sendto_silhouette.py --connection_type=bluetooth --bluetooth_addr=00:1B:41:33:44:55 yourfile.svg

# List visible BLE devices, then stop.
sendto_silhouette.py --connection_type=ble --bluetooth_scan=True yourfile.svg

# Plot over BLE using the cutter's advertised name.
sendto_silhouette.py --connection_type=ble --bluetooth_name="CAMEO 5 ALPHA-000000" yourfile.svg

# Select a BLE cutter by a platform-local identifier instead.
sendto_silhouette.py --connection_type=ble --bluetooth_identifier="LOCAL-IDENTIFIER" yourfile.svg
```

---

## Design Tips

### Getting an outline of a vector object

Tip: **Silhouette Cut Contour** does this automatically, including for bitmaps and for many designs at once (see [Generate the cut contour](#generate-the-cut-contour)). The manual steps below remain useful for one-off shapes.

1. Path > Break Apart
1. Path > Union
1. Depening on your sticker cutting requirement:
 - Path > Inset
 - Path > Outset
 - Path > Dynamic Offset


### Getting an outline of a bitmap object

1. Path > Trace Bitmap
  1. Use brightness cutoff detection mode. 
  1. Select threshold to get as much detail of the object in the image.
  1. Press Apply
1. Select all the vector outlines that was detected and generated
1. Path > Break Apart
1. Path > Union
1. Depening on your sticker cutting requirement:
 - Path > Inset
 - Path > Outset
 - Path > Dynamic Offset

 
