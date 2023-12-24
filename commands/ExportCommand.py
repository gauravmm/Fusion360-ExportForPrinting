import dataclasses
import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import adsk.cam
import adsk.core
import adsk.fusion
from adsk.core import (
    BoolValueCommandInput,
    Command,
    CommandInputs,
    SelectionCommandInput,
)
from adsk.fusion import Component, MoveFeature, Occurrence, OccurrenceList

from .. import config

# Import the entire apper package
from ..apper import apper
from ..apper.apper import Fusion360Utilities as utils

config_file_name = "export_for_printing.json"

VALID_ORIENTATIONS = ["x", "y", "z", "-x", "-y", "-z"]


@dataclass
class ComponentExportConfig:
    """Configuration for exporting a component."""

    # The component to export
    name: str = None
    # The basename to export to
    to: str = None
    # Orientation
    up: Optional[str] = None
    # Overrides
    fmt: Optional[str] = None
    count: Optional[int] = None

    def to_dict(self) -> Dict:
        """Convert this object to a dictionary."""
        rv = {
            "name": self.name,
            "to": self.to,
        }
        if self.orientation is not None:
            rv["up"] = self.up
        if self.fmt is not None:
            rv["fmt"] = self.fmt
        if self.count is not None:
            rv["count"] = self.count
        return rv


@dataclass
class ExportConfig:
    """Configuration for exporting a design."""

    fmt: Optional[str] = None
    components: List[ComponentExportConfig] = field(default_factory=list)
    modified: Optional[datetime] = None

    @classmethod
    def generate(cls, component_names: Iterable[str]) -> "ExportConfig":
        """Create an export configuration from the root component."""
        return cls(
            fmt="stl",
            components=[
                ComponentExportConfig(name=cmp, to=cmp.lower().replace(" ", "_"))
                for cmp in component_names
            ],
        )
        # TODO: Support exporting with subdirectories.


def parse_file(filename: Path, counts: Optional[Dict[str, int]]) -> ExportConfig:
    """Parse a file and return the configuration."""
    obj = json.loads(filename.read_text())
    version = int(obj.get("v", 0))
    assert version == 1, f"Unknown version {version}"

    fmt = obj.get("fmt", None)
    components = []
    for cmp_dict in obj.get("components", []):
        cmp = ComponentExportConfig(**cmp_dict)
        # If the count is not specified, use the count from the counts dictionary.
        if cmp.count is None and counts is not None:
            cmp.count = counts.get(cmp.name, 1)
        components.append(cmp)

    return ExportConfig(
        fmt=fmt,
        components=components,
        modified=datetime.fromtimestamp(filename.stat().st_mtime).isoformat(),
    )


def emit_file(filename: Path, config: ExportConfig):
    """Emit a file with the given configuration."""
    obj = {
        "v": 1,
        "fmt": config.fmt,
        "components": sorted(
            (cmp.to_dict() for cmp in config.components),
            key=lambda x: x["name"],
        ),
    }
    filename.write_text(json.dumps(obj, indent=2))


# Performs a recursive traversal of an entire assembly structure, counting the number of occurrences of each component.
def recursiveEnumerateComponents(
    rootOcc: Occurrence | Component,
) -> Dict[str, Component]:
    rv: Dict[str, Component] = {}
    occ: Occurrence
    if isinstance(rootOcc, Component):
        # If the root is a component, add it to the list of available components to export.
        rv[rootOcc.name] = rootOcc
        for occ in rootOcc.occurrences:
            rv.update(recursiveEnumerateComponents(occ))
    else:
        # Handle it as an occurrence:
        rv[rootOcc.component.name] = rootOcc.component
        for occ in rootOcc.childOccurrences:
            # We don't merge the lists here, because every component will appear at most once.
            rv.update(recursiveEnumerateComponents(occ))

    return rv


def export(main_cfg: ExportConfig, output_dir: Path, root: Occurrence | Component):
    ao = apper.AppObjects()

    # Iterate over all components from the root and assemble a list of components to export.
    all_components = recursiveEnumerateComponents(root)
    components: List[ComponentExportConfig, Component] = []
    for cmp_cfg in main_cfg.components:
        if cmp := all_components.get(cmp_cfg.name, None):
            # We found a component with the given name.
            components.append((cmp_cfg, cmp))

    # Set styles of progress dialog.
    progressDialog = ao.ui.createProgressDialog()
    progressDialog.cancelButtonText = "Cancel"
    progressDialog.isBackgroundTranslucent = False
    progressDialog.isCancelButtonShown = True
    # Show dialog
    progressDialog.show(
        "Progress Dialog", "Exporting component %v of %m", 0, len(components)
    )

    # Create a file to manage version control:
    version_control_file = output_dir / Path(config_file_name).with_suffix(
        ".version.json"
    )
    version_control: Dict[str, Dict[str, str | int]] = {}
    if version_control_file.exists():
        # Merge the changes into the existing file:
        version_control = json.loads(version_control_file.read_text())

    for i, (cfg, cmp) in enumerate(components):
        # Update progress dialog
        progressDialog.progressValue = i
        progressDialog.progressMessage = "Exporting component %v of %m"

        # Generate the filename:
        file_to = cfg.to
        file_ext = cfg.fmt or main_cfg.fmt

        if file_to.endswith(file_ext):
            # If the extension is already in the name, remove it.
            file_to = file_to[: -len(file_ext)]
        file_key = file_to

        # TODO: Allow this to be overridden in the config file.
        if cfg.count is not None:
            # Add the count to the filename:
            file_to += f"_x{cfg.count}"
        filename = f"{file_to}.{file_ext}"
        filepath = output_dir / filename

        old_version = version_control.get(file_key, None)
        if old_version is not None:
            # Check if the file has changed since the last export.
            if (
                old_version["component"] == cmp.name
                and old_version["revisionId"] == cmp.revisionId
                and filepath.exists()
                and (main_cfg.modified and old_version["changed"] < main_cfg.modified)
            ):
                # The file has not changed since the last export, and the same config file
                # was used to generate it. Skip it.
                # TODO: Because of the way we handle rotations (by mutating the component temporarily),
                # the revision Id will change even if the component has not changed. This should be fixed
                # by copying and then rotating the component. Until then, this will only work for unrotated
                # components.
                # ao.print_msg(f"Skipping unchanged file {filename}")
                continue

            # If the file name has changed, delete the old file:
            if old_version["filename"] != str(filepath):
                old_filename = output_dir / old_version["filename"]
                if old_filename.exists():
                    old_filename.unlink()

        version_control[file_key] = {
            "component": cmp.name,
            "filename": str(filepath),
            "revisionId": cmp.revisionId,
            "fromDocument": ao.root_comp.name,
            "changed": datetime.now().isoformat(),
        }

        vector_to = {
            "-x": adsk.core.Vector3D.create(1, 0, 0),
            "-y": adsk.core.Vector3D.create(0, 1, 0),
            "-z": adsk.core.Vector3D.create(0, 0, 1),
            "x": adsk.core.Vector3D.create(-1, 0, 0),
            "y": adsk.core.Vector3D.create(0, -1, 0),
            "z": adsk.core.Vector3D.create(0, 0, -1),
        }

        # Rotate the component to the desired orientation:
        newMoveFeature: Optional[MoveFeature] = None
        if cfg.up is not None and cfg.up != "z":
            assert cfg.up in VALID_ORIENTATIONS, f"Invalid orientation {cfg.up}"

            transform = adsk.core.Matrix3D.create()
            transform.setToRotateTo(vector_to[cfg.up], vector_to["z"])

            # Create a move feature
            itemsToMove = adsk.core.ObjectCollection.create()
            # TODO: Support exporting with mesh bodies, not just BRep.
            for body in cmp.bRepBodies:
                itemsToMove.add(body)
            moveFeats = cmp.features.moveFeatures
            moveFeatureInput = moveFeats.createInput2(itemsToMove)
            moveFeatureInput.transform = transform
            newMoveFeature = moveFeats.add(moveFeatureInput)

        # Ensure the directory exists.
        filepath.parent.mkdir(parents=True, exist_ok=True)

        # Get the export manager from the active design.
        exportMgr = ao.design.exportManager
        exportOptions = exportMgr.createSTLExportOptions(cmp, str(filepath))
        # TODO: Support other formats.
        # TODO: Support other refinement levels.
        exportOptions.meshRefinement = (
            adsk.fusion.MeshRefinementSettings.MeshRefinementMedium
        )

        # Export the occurrence to STL.
        exportMgr.execute(exportOptions)

        # Delete the move feature:
        if newMoveFeature is not None:
            newMoveFeature.deleteMe()

        # Check if the cancel button was pressed.
        if progressDialog.wasCancelled:
            break
        # Update progress value of progress dialog
        progressDialog.progressValue = i + 1

    # Hide the progress dialog at the end.
    progressDialog.hide()

    # Write the updated files to a file:
    version_control_file.write_text(json.dumps(version_control, indent=2))


app_name = "ExportForPrinting"


def update_settings(**config: Dict[str, Any]):
    ao = apper.AppObjects()
    file_name = ao.document.name

    # Read the settings file, merge in the file settings, and write it back:
    settings = utils.read_settings(app_name)
    settings[file_name] = config
    utils.write_settings(app_name, settings)


def get_settings() -> Dict[str, Any]:
    ao = apper.AppObjects()
    file_name = ao.document.name

    # Read the settings file, merge in the file settings, and write it back:
    return utils.read_settings(app_name).get(file_name, {})


class ExportCommand(apper.Fusion360CommandBase):
    # Run whenever a user makes any change to a value or selection in the addin UI
    # Commands in here will be run through the Fusion processor and changes will be reflected in  Fusion graphics area
    def on_preview(self, command, inputs, args, input_values):
        pass

    # Run after the command is finished.
    # Can be used to launch another command automatically or do other clean up.
    def on_destroy(self, command, inputs, reason, input_values):
        pass

    # Run when any input is changed.
    # Can be used to check a value and then update the add-in UI accordingly
    def on_input_changed(self, command, inputs, changed_input, input_values):
        # Selections are returned as a list so lets get the first one
        all_selections = input_values.get("selection_input_id", None)
        if all_selections is not None and len(all_selections) > 0:
            pass
            # Update the text of the string value input to show the type of object selected
            # TODO: Show how many matching bodies will be exported.
            # text_box_input = inputs.itemById("text_box_input_id")
            # text_box_input.text = "TODO: Count matching components."

        # If the user has selected the "Change" option in the drop down then show the folder dialog
        dir_select_btn: BoolValueCommandInput = inputs.itemById("dir_select_btn")
        if dir_select_btn.value:  # The user has selected the "Change" option
            dir_select_btn.value = False
            ao = apper.AppObjects()
            dirDialog = ao.ui.createFolderDialog()
            dirDialog.title = "Select destination directory"
            dialogResult = dirDialog.showDialog()
            if dialogResult == adsk.core.DialogResults.DialogOK:
                filename = dirDialog.folder
                # Update the drop down to show the selected folder:
                inputs.itemById("dir_selected").text = filename

    # Run when the user presses OK
    # This is typically where your main program logic would go
    def on_execute(self, command, inputs, args, input_values):
        ao = apper.AppObjects()
        output_dir = Path(inputs.itemById("dir_selected").text)
        # Ensure the directory exists.
        output_dir.mkdir(parents=True, exist_ok=True)

        # Get the selected object
        sel_obj = input_values["selection_input_id"][0]
        if not isinstance(sel_obj, (Occurrence, adsk.fusion.Component)):
            ao.ui.messageBox("Please select a component to export.")
            return
        # Write the last used directory and selection to a file:
        update_settings(
            last_dir=str(output_dir),
            last_selection=sel_obj.name if isinstance(sel_obj, Occurrence) else "_root",
        )

        config_file = output_dir / config_file_name
        if not config_file.exists():
            # Create an export config from the global tree, and emit it to a file.
            emit_file(config_file, ExportConfig.generate(self.component_counts.keys()))

            # Display a message to the user
            ao.ui.messageBox(
                "Created new export configuration file. Please edit it and run this script again."
            )
            return

        # Load the config file:
        export_cfg = parse_file(config_file, self.component_counts)
        export(export_cfg, output_dir, sel_obj)

    # Run when the user selects your command icon from the Fusion 360 UI
    # Typically used to create and display a command dialog box
    # The following is a basic sample of a dialog UI

    def on_create(self, command, inputs):
        ao = apper.AppObjects()

        settings = get_settings()
        # Get the last used directory and selection from the file:
        last_dir = settings.get("last_dir", "")
        self.last_selection = settings.get("last_selection", None)

        # File selector:
        # Read Only Text Box
        inputs.addTextBoxCommandInput("dir_selected", "Export to: ", last_dir, 1, True)
        dir_select_btn = inputs.addBoolValueInput("dir_select_btn", "Change", False)
        dir_select_btn.tooltip = "Select the directory to export to"

        selInp: SelectionCommandInput = inputs.addSelectionInput(
            "selection_input_id",
            "Top component to export",
            "Select a component, and it (and its children) will be exported.",
        )
        selInp.addSelectionFilter("Occurrences")
        self.selInp = selInp

        # Read Only Text Box
        # inputs.addTextBoxCommandInput(
        #    "text_box_input_id", "Selection Type: ", "Nothing Selected", 1, True
        # )

        # Count occurrences of all components in the tree. We need this to count the effective number of copies:
        self.component_counts = recursiveCountOccurences(
            ao.root_comp.occurrences.asList
        )

    def on_activate(self, command: Command, inputs: CommandInputs, args, input_values):
        super().on_activate(command, inputs, args, input_values)

        last_selection = getattr(self, "last_selection", None)
        if last_selection is not None:
            # Look up the component:
            ao = apper.AppObjects()
            if last_selection == "_root":
                item = ao.root_comp
            else:
                item = ao.root_comp.occurrences.itemByName(last_selection)
            if item is not None:
                self.selInp.addSelection(item)


# Performs a recursive traversal of an entire assembly structure, counting the number of occurrences of each component.
def recursiveCountOccurences(occurrences: OccurrenceList) -> Dict[str, int]:
    rv = defaultdict(int)
    occ: Occurrence

    for occ in occurrences:
        rv[occ.component.name] += 1

    # Now that we have counted the unique components, we recur on the first occurrence of each component, and multiply the count by the number of occurrences.
    for occ in occurrences:
        if occ.name.endswith(":1"):
            child = recursiveCountOccurences(occ.childOccurrences)
            for key, count in child.items():
                rv[key] += count * rv[occ.component.name]

    return rv
