# at-ai-editor-recommender

Setup python environment with uv

~~~bash
uv sync
~~~

To run manually, set profile for AWS credentials to connect to Bedrock. This profile is the aws sso login for the AWS AI account, in this case sandbox

~~~bash
aws sso login --profile gts-eks-poc-sandbox
~~~

Export AWS credentials as environment variables. In EKS, these credentials will be automatically injected using IRSA

~~~bash
aws configure export-credentials --profile gts-eks-poc-sandbox --format env
~~~

Example output to run:

~~~bash
export AWS_ACCESS_KEY_ID=ASOAUE14KWN5PBMNL24B
export AWS_SECRET_ACCESS_KEY=jzwmT3+ugLa67AK2BQAr0Cv/W2EYN1983HrePCG8
export AWS_SESSION_TOKEN=IQoJb3JpZ2luX2VjEML//////////wEaCXVzLWVhc3QtMSJIMEYCIQCvB1ma7jj26wC09e1jLr+1K3CKB80yfXRN9Paufo9VJwIhAJ/nIiGxUR/pNi3BkDmHyKK75xRKmcbL8cNLaObkxtXxKogDCGsQABoMMjg4NzYxWzU0NDkwIgzKUr/Epfj4U+raYc4q5QKwbeEyimpWrGFWxO6yWipKURSf41JSX+04aprDSq8QJdZ9wvYwYXxrGMiktZR1M88v/ShI/oWRoLdfPz5Q7dAuxOyy/ZRirqI+5moBmiRYf0GzW3vuzmiOHevF44W0WvBhUM81waclBBuqvmiPP5xWZ0nMgypO4Efg4n1jNRWjuMN5Bak6CwkB1cXyQKREcMo5PcZmZRWXlfaKhgYjGQSYGGE9Z2Cqc6s9BwdOVejI6YdDgTgy2cRdenxJXxibZhzwpB5aqC2e9ZZMsU1WGpUx45lt3gyDi6Zq5DaVMHSVwcUMb8NySDK3Oe1vWVcdSnNuHnt5u3d8DRewFd1ijrmp3HYG8KmMWkXGWH/splq0NlVqnbhs7WewU445/ovLQXnWwsQKQsL9NYdRwdprqJEdWt4wGmyCCrqkaI6OlLT5BkuOd3kPkMI+tvlzo9PiFtqe9A20BiSW532HwXhvZReoX8qEVYMwv/m7xwY6pQGi9jpt7xuGHJIcY+RsT0RNzcShKPtcTdR5jdd6ClIWtMYo5rHf6s465dYj/tW/J10/9kF0/IgsI+AqCS4eVNnJhCKj3dfashUT7eVER1J9ofHEu1lNo3Wk7UYXAVNPMdTSruJYoogJmwwNGx+ZGDb24aIMwoOnEx7M9Jw8PTpB4bYCLLZoKmBXb9U84dM5JraS/3p-uux+fzNRK1NwUk1HWD1MwR4=
export AWS_CREDENTIAL_EXPIRATION=2025-10-15T02:45:34+00:00
~~~

Run agent and can override any environment variables from .env if needed

~~~bash
EE_URL=http://prod-lnx-3006:8005/v1/processManuscript \
PORT=8013 \
uv run src/at_ai_editor_recommender/app.py
~~~

