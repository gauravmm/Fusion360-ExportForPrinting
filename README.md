# ExportForPrinting

Quickly and easily export Fusion360 designs for 3d printing, in a manner that works with git and 3d printing software. You put the configuration json in a new folder, run the Add-In, and it will export files from your design to the folder.

Here are the features:

1. Each component is exported once, with the required quantity in the filename (e.g. `part_x1.stl`).
2. Each time you run it, it will only overwrite only the changed files (saves time on large designs!)
3. The export folder is git-friendly, allowing for versioning and traceability.
4. You can specify which axis should be up in the config file, and the parts are rotated accordingly.
5. File versions and export times are tracked in a sidecar file, so you relate the git history to your Fusion 360 history.

## Workflow

You can see this project in action with my [Idis pedals](https://github.com/gauravmm/Idis-Pedals) project. Its a pretty complex project with lots of parts in different orientations and materials. For this, I have a Fusion360 project with all the parts, a git repo in a folder with exported STL files, and a Bambu/Orca Slicer project with all the printing set up.

To make a change, this is what I do:

 1. Modify the parts in Fusion360.
 2. Press the "Export for Printing" button.
 3. Select the modified components (or the root) and the export folder. Click `Ok`.
 4. (Wait for a few seconds while only the modified parts are exported.)
 5. Go to the slicer project and "Reload from disk" to update the parts, then slice and print.
 6. When I'm done, I commit the changes to the repository, including `export_for_printing.json` and `export_for_printing.version.json`.

## Configuration Options

The configuration file is a json file with the following options:

- `components`: a list of files to write to. Each component is an object with the following options:
  - `name`: The name of the component in Fusion360.
  - `to`: The filename relative to the export folder, without the extension.
  - `up`: (Optional) The axis that should be facing upwards in the exported files. Can be one of: `x`, `y`, `z`, `-x`, `-y`, `-z`. Defaults to `z`.
  - `fmt`: (Optional) The export format. Only `stl` is supported at the moment.
  - `count`: The number of copies to tag the file with. Defaults to the number of instances of the component in the design.
- `fmt`: the default export format. Only `stl` is supported at the moment.
- `v`: Version of the configuration file. Must be `1`.

## Features and Bugs

Feel free to open issues for feature requests or bugs. Pull requests are also welcome. The code is fairly straightforward, and TODOs are noted therein.

`ExportForPrinting` was written by `Gaurav Manek <gaurav@gauravmanek.com>`.
