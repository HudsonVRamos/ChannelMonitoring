#!/usr/bin/env python3
"""CDK App para a infraestrutura da Widevine PoC."""

import aws_cdk as cdk

from stacks.widevine_poc_stack import WidevinePoCStack


app = cdk.App()

project_name = app.node.try_get_context("project_name") or "widevine-poc"

WidevinePoCStack(
    app,
    f"{project_name}-stack",
    project_name=project_name,
    description="Infraestrutura para PoC de validação Widevine DRM com Playwright",
)

app.synth()
