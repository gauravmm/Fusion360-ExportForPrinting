import adsk.core
import traceback

import os

try:
    from . import config
    from .apper import apper

    # ************Samples**************
    # Basic Fusion 360 Command Base samples
    from .commands.ExportCommand import ExportCommand

    # Create our addin definition object
    my_addin = apper.FusionApp(config.app_name, config.company_name, False)
    my_addin.root_path = config.app_path

    # Creates a basic Hello World message box on execute
    my_addin.add_command(
        "Export for Printing",
        ExportCommand,
        {
            "cmd_description": "Export components to a directory",
            "cmd_id": "export_to_directory",
            "workspace": "FusionSolidEnvironment",
            "toolbar_panel_id": "SolidMakePanel",
            "cmd_resources": "command_icons",
            "command_visible": True,
            "command_promoted": True,
        },
    )

    app = adsk.core.Application.cast(adsk.core.Application.get())
    ui = app.userInterface

except:
    app = adsk.core.Application.get()
    ui = app.userInterface
    if ui:
        ui.messageBox("Initialization Failed: {}".format(traceback.format_exc()))

# Set to True to display various useful messages when debugging your app
debug = False


def run(context):
    my_addin.run_app()


def stop(context):
    my_addin.stop_app()
