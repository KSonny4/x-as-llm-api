FROM python:3.12-slim
WORKDIR /srv/keeper
COPY server.py smoke.py translate.py matrix.py aa.py inventory.py keyqueue.json ./
ENV PORT=8080
EXPOSE 8080
CMD ["python3", "server.py"]
