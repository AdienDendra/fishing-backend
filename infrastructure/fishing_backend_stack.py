from aws_cdk import (
    Stack, RemovalPolicy, Duration,
    aws_s3 as s3,
    aws_lambda as _lambda,
    aws_events as events,
    aws_events_targets as targets,
    aws_iam as iam,
)

import aws_cdk as cdk
from constructs import Construct


class FishingBackendStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        
        # ── S3 Bucket ──────────────────────────────────────────────────────────
        weather_cache_bucket = s3.Bucket(
            self,
            "WeatherCacheBucket",
            bucket_name="adiendendra-fishing-data",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            versioned=False,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            lifecycle_rules=[
                s3.LifecycleRule(
                    prefix="weather-cache/",
                    expiration=Duration.days(8),  # 7 hari forecast + 1 hari buffer
                )
            ],
        )

        gemini_param_arn = f"arn:aws:ssm:{self.region}:{self.account}:parameter/fishing-backend/gemini-api-key"

        # ── weather_processor (cron harian 08:00 UTC, pre-warm Botany Bay) ──────
        weather_processor_fn = _lambda.Function(
            self,
            "WeatherProcessorFunction",
            function_name="weather-processor",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=_lambda.Code.from_asset(
                "../lambda_functions/weather_processor",
            ),
            timeout=Duration.seconds(180),
            environment={
                "BUCKET_NAME": weather_cache_bucket.bucket_name,
            },
        )
        weather_processor_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["ssm:GetParameter"],
                resources=[gemini_param_arn],
            )
        )
        weather_cache_bucket.grant_put(weather_processor_fn, "weather-cache/*")

        weather_processor_rule = events.Rule(
            self,
            "WeatherProcessorSchedule",
            schedule=events.Schedule.cron(
                minute="0",
                hour="8",
            ),
        )
        weather_processor_rule.add_target(targets.LambdaFunction(weather_processor_fn))

        # ── weather_analysis (async Gemini, dipanggil fire-and-forget) ──────────
        weather_analysis_fn = _lambda.Function(
            self,
            "WeatherAnalysisFunction",
            function_name="weather-analysis",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=_lambda.Code.from_asset(
                "../lambda_functions/weather_analysis",
            ),
            timeout=Duration.seconds(180),  # Gemini bisa lambat, sama dengan processor
            environment={
                "BUCKET_NAME": weather_cache_bucket.bucket_name,
            },
        )
        weather_analysis_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["ssm:GetParameter"],
                resources=[gemini_param_arn],
            )
        )
        
        weather_cache_bucket.grant_put(weather_analysis_fn, "weather-cache/*")
        weather_cache_bucket.grant_read(weather_analysis_fn, "weather-cache/*")

        # ── weather_handler (API Gateway triggered, cache-aside) ─────────────────
        weather_handler_fn = _lambda.Function(
            self,
            "WeatherHandlerFunction",
            function_name="weather-handler",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=_lambda.Code.from_asset(
                "../lambda_functions/weather_handler",
            ),
            timeout=Duration.seconds(30),   # Cukup — Gemini ada di weather_analysis
            environment={
                "BUCKET_NAME": weather_cache_bucket.bucket_name,
                "ANALYSIS_FUNCTION_NAME": weather_analysis_fn.function_name,
            },
        )
        weather_cache_bucket.grant_read(weather_handler_fn, "weather-cache/*")
        weather_cache_bucket.grant_put(weather_handler_fn, "weather-cache/*")
        weather_handler_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["lambda:InvokeFunction"],
                resources=[weather_analysis_fn.function_arn],
            )
        )