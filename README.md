# Sistema de credenciales Cruztitla

Aplicacion web con FastAPI, OpenCV y OCR para procesar una identificacion, enderezarla, detectar el rostro, extraer nombre/fecha y generar una credencial final sobre `backend/static/plantilla.png`.

## Estructura

- `backend/main.py`: API FastAPI y archivos descargables.
- `backend/image_pipeline.py`: correccion de perspectiva, orientacion, rostro y recortes.
- `backend/ocr_clients.py`: extraccion de nombre y fecha.
- `backend/credential_composer.py`: composicion de la credencial PNG.
- `backend/docx_formatter.py`: generacion del formato Word.
- `backend/static/plantilla.png`: plantilla base de la credencial.
- `frontend/`: interfaz HTML/CSS/JS servida por FastAPI.
- `formato credencial.docx`: plantilla Word para descargar el formato completo.
- `render.yaml`: configuracion base para Render.

## Ejecutar localmente

```powershell
cd "C:\Users\Einar\Desktop\equipo de futbol\backend"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Abre:

```text
http://127.0.0.1:8000
```

## Variables opcionales

El OCR local con RapidOCR funciona sin API. Para mejorar la precision en documentos dificiles puedes configurar OpenAI o Gemini:

```powershell
$env:OPENAI_API_KEY="tu_api_key"
$env:OPENAI_VISION_MODEL="gpt-4o"
```

```powershell
$env:GEMINI_API_KEY="tu_api_key"
$env:GEMINI_MODEL="gemini-1.5-pro"
```

## Despliegue en Render

1. Sube este proyecto a GitHub.
2. En Render crea un nuevo **Blueprint** y selecciona este repo.
3. Render leera `render.yaml`.
4. El servicio usara:

```text
Build Command: pip install -r backend/requirements.txt
Start Command: cd backend && uvicorn main:app --host 0.0.0.0 --port $PORT
```

El almacenamiento `backend/storage/` es temporal. Las credenciales se generan para descarga inmediata, pero no se deben considerar archivo historico permanente en Render sin un disco persistente o almacenamiento externo.

### Si lo creas manual como Web Service

Usa los mismos comandos:

```text
Build Command: pip install -r backend/requirements.txt
Start Command: cd backend && uvicorn main:app --host 0.0.0.0 --port $PORT
Health Check Path: /api/health
```

Y agrega estas variables en **Environment**:

```text
PYTHON_VERSION=3.11.9
APP_TIMEZONE=America/Mexico_City
OCR_PROVIDER=api_only
STORAGE_DIR=/tmp/cruztitla-storage
OPENCV_NUM_THREADS=1
OMP_NUM_THREADS=1
OPENBLAS_NUM_THREADS=1
```

`OCR_PROVIDER=api_only` evita cargar OCR local pesado en Render. Para extraccion automatica en la nube, agrega tambien `OPENAI_API_KEY` o `GEMINI_API_KEY`. Si no agregas API, el sistema procesara la foto y permitira llenar/corregir datos manualmente.

Si ves "sesion no encontrada", normalmente significa que Render reinicio el servicio y se perdieron los archivos temporales de `STORAGE_DIR`. Vuelve a subir la identificacion. Para conservar sesiones durante reinicios, agrega un disco persistente en Render y apunta `STORAGE_DIR` al mount path de ese disco.

## Keep-alive opcional

El workflow `.github/workflows/keep-render-awake.yml` hace ping cada 10 minutos si existe el secreto:

```text
RENDER_KEEPALIVE_URL=https://tu-app.onrender.com/api/health
```

Configuralo en GitHub:

```text
Settings -> Secrets and variables -> Actions -> New repository secret
```

Tambien puedes ejecutarlo manualmente desde la pestana **Actions**.

## Privacidad

No subas identificaciones reales al repo. `.gitignore` excluye `backend/storage/` y las imagenes locales de prueba.
