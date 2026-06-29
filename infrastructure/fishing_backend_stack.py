from aws_cdk import (
    Stack, RemovalPolicy, Duration,
    aws_s3 as s3,
    aws_lambda as _lambda,
    aws_events as events,
    aws_events_targets as targets,
    aws_iam as iam,
    aws_apigatewayv2 as apigwv2,
    aws_apigatewayv2_integrations as integrations,
)

import aws_cdk as cdk

from aws_cdk import aws_certificatemanager as acm
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
        
        # ── weather_activity (Lambda triggered for forecast fish activity) ────────

        weather_activity_fn = _lambda.Function(
            self,
            "WeatherActivityFunction",
            function_name="weather-activity",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=_lambda.Code.from_asset(
                "../lambda_functions/weather_activity",
            ),
            timeout=Duration.seconds(60),
            environment={
                "BUCKET_NAME": weather_cache_bucket.bucket_name,
                "ANALYSIS_FUNCTION_NAME": weather_analysis_fn.function_name,
            },
        )
        weather_cache_bucket.grant_read(weather_activity_fn, "weather-cache/*")
        weather_cache_bucket.grant_put(weather_activity_fn, "weather-cache/*")

        weather_activity_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["lambda:InvokeFunction"],
                resources=[weather_analysis_fn.function_arn],
            )
        )

        

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
                "ACTIVITY_FUNCTION_NAME": weather_activity_fn.function_name,
            },
        )
        weather_cache_bucket.grant_read(weather_handler_fn, "weather-cache/*")
        weather_cache_bucket.grant_put(weather_handler_fn, "weather-cache/*")
        weather_handler_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["lambda:InvokeFunction"],
                resources=[weather_activity_fn.function_arn],
            )
        )

        # ── API Gateway HTTP API ───────────────────────────────────────────────
        http_api = apigwv2.HttpApi(
            self,
            "FishingWeatherApi",
            api_name="fishing-weather-api",
            cors_preflight=apigwv2.CorsPreflightOptions(
            allow_origins=[
                "https://fishing.adiendendra.com",
                "http://localhost:1313",
                "http://localhost:8080",
            ],
            allow_methods=[apigwv2.CorsHttpMethod.GET],
            allow_headers=["Content-Type"],
            ),
        )

        # Route GET /weather → weather_handler Lambda
        http_api.add_routes(
            path="/weather",
            methods=[apigwv2.HttpMethod.GET],
            integration=integrations.HttpLambdaIntegration(
                "WeatherHandlerIntegration",
                weather_handler_fn,
            ),
        )

        # Custom domain — api.fishing.adiendendra.com
        domain_name = apigwv2.DomainName(
            self,
            "ApiDomainName",
            domain_name="api.fishing.adiendendra.com",
            certificate=acm.Certificate.from_certificate_arn(
                self,
                "ApiCertificate",
                "arn:aws:acm:ap-southeast-2:121861012913:certificate/27efc763-43a6-4ae8-89a8-b8fe7d3016e4",
            ),
        )

        apigwv2.ApiMapping(
            self,
            "ApiMapping",
            api=http_api,
            domain_name=domain_name,
        )