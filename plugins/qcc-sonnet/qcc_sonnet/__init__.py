"""Sonnet S-parameter export for quantcore-circuits (wraps KQC ``export_sonnet``)."""

from quantcore_circuits.plugins import AnalysisPlugin


def export(setup, job_dir, **settings):
    from kqcircuits.simulations.export.sonnet.sonnet_export import export_sonnet  # pylint: disable=C0415

    export_sonnet([setup.simulation], job_dir, **settings)


SONNET = AnalysisPlugin(
    name="sonnet_s",
    kind="capacitance",  # cut-out with edge ports on crossing lines
    solver="sonnet",
    export=export,
    defaults={"detailed_resonance": False, "lower_accuracy": False},
    description="Sonnet .son project (KQC export_sonnet)",
)
