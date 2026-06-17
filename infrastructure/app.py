#!/usr/bin/env python3
import aws_cdk as cdk

from fishing_backend_stack import FishingBackendStack

app = cdk.App()
FishingBackendStack(app, "FishingBackendStack")

app.synth()
