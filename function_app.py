"""
Azure Functions v2 Python programming model entry point.

Registers the Argus weekly timer trigger. The schedule is read from the
ARGUS_SCHEDULE app setting (set by the Bicep template; default: every Monday
9am UTC = "0 0 9 * * 1").

This file must exist at the repository root for `func azure functionapp publish`
to detect and register the function.
"""

import azure.functions as func

from entrypoints.azure_function import main as argus_main

app = func.FunctionApp()


@app.timer_trigger(
    schedule="%ARGUS_SCHEDULE%",
    arg_name="mytimer",
    run_on_startup=False,
)
def argus_scan(mytimer: func.TimerRequest) -> None:
    """Weekly Argus cost scan triggered by Azure Function timer."""
    argus_main(mytimer)
