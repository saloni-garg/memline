# Standard image build, for any Docker host or a future flyctl deploy.
# The current Fly Machines deployment boots from a public python image and
# fetches this same code at start; see DEPLOY.md.
FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
ENV MEMLINE_DB=/data/memline.db
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
