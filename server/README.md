# FastAPI Skill Server

This server exposes the two endpoints expected by the sync client:

- `GET /manifest.json`: returns the manifest used by `sync_skills.py`
- `GET /skills/{skill_path}`: returns the raw skill file content

When S3 is configured, the server reads skills from the bucket first. If S3 has a connectivity failure, the server falls back to local files under `server/skills`.

## Folder Layout

- `main.py`: FastAPI application
- `requirements.txt`: runtime dependencies
- `skills/`: local skill content served by the API

## Install

```powershell
python -m pip install -r .\server\requirements.txt
```

## AWS Lambda Container

The server can be packaged as an AWS Lambda-compatible container image. The FastAPI app is adapted to Lambda with `Mangum`, and the image uses the AWS Python 3.11 Lambda base image.

Build the image from the repository root:

```powershell
docker build -t skill-server-lambda -f .\server\Dockerfile .
```

For AWS Lambda deployment, push the image to ECR and create a Lambda function from that image. The handler is already baked into the image as `server.lambda_handler.handler`.

Local Lambda-style container run:

```powershell
docker run --rm -p 9000:8080 skill-server-lambda
```

After the container starts, invoke it with an API Gateway v2 event payload or front it with a Lambda Function URL or API Gateway in AWS.

## Run

```powershell
$env:SKILL_SERVER_TOKEN = "dev-token"
uvicorn server.main:app --host 0.0.0.0 --port 8000
```

## Run With S3

```powershell
$env:SKILL_SERVER_TOKEN = "dev-token"
$env:SKILL_S3_BUCKET = "my-skill-bucket"
$env:SKILL_S3_PREFIX = "skills"
$env:AWS_REGION = "us-east-1"
uvicorn server.main:app --host 0.0.0.0 --port 8000
```

## Client Configuration

Point the sync client at:

- Manifest URL: `http://localhost:8000/manifest.json`
- API token: `dev-token`

Example:

```powershell
$env:SKILL_MANIFEST_URL = "http://localhost:8000/manifest.json"
$env:SKILL_API_TOKEN = "dev-token"
python .\sync_skills.py
```

## Environment Variables

- `SKILL_CONTENT_DIR`: optional alternate directory for served skill files. Defaults to `server/skills`.
- `SKILL_SERVER_TOKEN`: optional bearer token required by both endpoints. If unset, the server allows anonymous access.
- `SKILL_S3_BUCKET`: optional S3 bucket name. If set, the server attempts to read skill files from this bucket first.
- `SKILL_S3_PREFIX`: optional prefix inside the S3 bucket. Defaults to the bucket root.
- `SKILL_S3_ENDPOINT_URL`: optional custom S3-compatible endpoint for MinIO or other compatible services.
- `AWS_REGION` or `AWS_DEFAULT_REGION`: optional AWS region used by the S3 client.

## Notes

- The manifest is generated dynamically from S3 when `SKILL_S3_BUCKET` is configured, otherwise from `server/skills`.
- If S3 list or download calls fail because of a connection problem, the server falls back to local files instead of failing the request.
- Responses include `X-Skill-Source` with `s3`, `local`, or `local-fallback`.
- Path traversal is blocked before files are returned.
- `version` is emitted as the current UTC timestamp each time the manifest is requested.
- The Lambda container image includes the local `server/skills` directory, so fallback content is available even when the function is not connected to S3.