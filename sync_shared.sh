#!/bin/bash
SHARED="lambda_functions/shared"
TARGETS=("lambda_functions/weather_processor" "lambda_functions/weather_activity" "lambda_functions/weather_handler" "lambda_functions/weather_analysis")

for target in "${TARGETS[@]}"; do
    cp "$SHARED/ai_analysis.py" "$target/"
    cp "$SHARED/config.py" "$target/"
    cp "$SHARED/weather_data.py" "$target/"
    cp "$SHARED/astronomy.py" "$target/"
    cp "$SHARED/cache_keys.py" "$target/"
    cp "$SHARED/fishing_activity.py" "$target/"
    echo "✅ Synced shared files to $target"
done
