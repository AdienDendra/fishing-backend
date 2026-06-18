from aws_cdk import (
    Stack, RemovalPolicy, Duration,
    aws_s3 as s3,
    aws_lambda as _lambda,
    aws_events as events,
    aws_events_targets as targets,
    aws_iam as iam,
)

from constructs import Construct


class FishingBackendStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        weather_cache_bucket = s3.Bucket(
            self,
            "WeatherCacheBucket",
            bucket_name="adiendendra-fishing-data",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            versioned=False,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        weather_processor_fn = _lambda.Function(
            self,
            "WeatherProcessorFunction",
            function_name="weather-processor",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=_lambda.Code.from_asset("../lambda_functions/weather_processor"),
            timeout=Duration.seconds(30),
            environment={
                "BUCKET_NAME": weather_cache_bucket.bucket_name,
            },
        )

        gemini_param_arn = f"arn:aws:ssm:{self.region}:{self.account}:parameter/fishing-backend/gemini-api-key"
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
            schedule=events.Schedule.rate(Duration.hours(3)),
        )
        weather_processor_rule.add_target(targets.LambdaFunction(weather_processor_fn))