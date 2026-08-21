#!/usr/bin/env python3
"""CDK App para a infraestrutura da Widevine PoC."""

import aws_cdk as cdk

from stacks.widevine_poc_stack import WidevinePoCStack
from stacks.ec2_monitor_stack import EC2MonitorStack


app = cdk.App()

project_name = app.node.try_get_context("project_name") or "widevine-poc"
env = cdk.Environment(account="761018874615", region="us-east-1")

WidevinePoCStack(
    app,
    f"{project_name}-stack",
    project_name=project_name,
    description="Infraestrutura para PoC de validação Widevine DRM com Playwright",
    env=env,
)

EC2MonitorStack(
    app,
    f"{project_name}-ec2-stack",
    project_name=project_name,
    description="EC2 para monitoramento SKY+ — Fase 1 (Chrome + Xvfb + VNC)",
    env=env,
)

app.synth()
