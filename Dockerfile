# Hosted Biomarker Timeline web service (webapp.py), for Railway.
#
# WeasyPrint (>=53) renders PDFs with Pango/HarfBuzz/Fontconfig rather than
# cairo, so those system libraries must be present in the image. They are
# installed below; everything else is pure-Python wheels from requirements.txt.

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MPLBACKEND=Agg \
    PORT=8080

# System libraries WeasyPrint needs to render text and PDFs.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libharfbuzz0b \
        libfontconfig1 \
        libffi8 \
        fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY . .

EXPOSE 8080

# One worker with threads keeps memory low (WeasyPrint + matplotlib + PyMuPDF are
# heavy) while still handling concurrent requests. The long timeout gives the AI
# vision pass (many Claude calls per scanned report) room to finish.
CMD ["sh", "-c", "gunicorn webapp:app --bind 0.0.0.0:${PORT:-8080} --workers 1 --threads 4 --timeout 300 --access-logfile -"]
