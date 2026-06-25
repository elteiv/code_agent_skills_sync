FROM public.ecr.aws/lambda/python:3.11

WORKDIR ${LAMBDA_TASK_ROOT}

COPY server/requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY server ./server

ENV PYTHONPATH=${LAMBDA_TASK_ROOT}

CMD ["server.lambda_handler.handler"]