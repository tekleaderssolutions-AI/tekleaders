import importlib.util
import json
import os
from pathlib import Path

from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

import pdfplumber
from dotenv import load_dotenv
from io import BytesIO

ROOT = Path(__file__).resolve().parent.parent


def _load_jd_service():
    load_dotenv(ROOT / ".env", override=True)
    service_path = ROOT / "jd_openai_service.py"
    spec = importlib.util.spec_from_file_location("jd_openai_service_v4", service_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {service_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def index(request):
    return HttpResponse(
        "Django is running. For the full app use FastAPI: double-click RUN_HIRING_SERVER.bat",
        content_type="text/plain",
    )


@require_GET
def api_health(request):
    return JsonResponse(
        {
            "status": "wrong_port",
            "app": "django",
            "use_instead": "http://127.0.0.1:8001/api/health",
            "admin": "http://127.0.0.1:8001/admin",
            "instruction": "Stop manage.py runserver. Run RUN_HIRING_SERVER.bat instead.",
        }
    )


@csrf_exempt
@require_POST
def init_db(request):
    try:
        from django.core.management import call_command

        call_command("init_db")
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)
    return JsonResponse({"status": "ok", "message": "migrations run"})


def _extract_pdf_text(contents: bytes) -> str:
    with pdfplumber.open(BytesIO(contents)) as pdf:
        return "\n".join([page.extract_text() or "" for page in pdf.pages])


@csrf_exempt
@require_POST
def analyze_jd_pdf(request):
    file = request.FILES.get("file")
    job_id = request.POST.get("job_id")
    source_url = request.POST.get("source_url")
    client_id = request.POST.get("client_id")
    if not file:
        return JsonResponse({"detail": "file required"}, status=400)

    if not file.name.lower().endswith(".pdf"):
        return JsonResponse({"detail": "Only PDF supported"}, status=400)

    contents = file.read()
    raw_jd_text = _extract_pdf_text(contents)
    if not raw_jd_text.strip():
        return JsonResponse({"detail": "no text extracted"}, status=400)

    target_client_id = client_id if client_id and client_id.strip() else "60e80ea2-ae7f-46d6-b30d-f73293036729"

    try:
        jd_mod = _load_jd_service()
        memory_json = jd_mod.process_jd_upload(
            raw_jd_text=raw_jd_text,
            job_id=job_id,
            source_url=source_url,
            created_by="jd_analyzer_agent_pdf",
            client_id=target_client_id,
        )
    except Exception as e:
        err = str(e)
        if "gemini" in err.lower() or "generativelanguage" in err.lower():
            return JsonResponse(
                {
                    "detail": "Gemini must not be used. Run RUN_HIRING_SERVER.bat (FastAPI), not Django.",
                },
                status=500,
            )
        return JsonResponse({"detail": f"JD-OpenAI-v4 error: {err}"}, status=500)

    return JsonResponse(memory_json)


@csrf_exempt
@require_POST
def upload_resumes(request):
    from resume_agent import process_resume_text
    from resume_text_extractor import (
        expand_upload,
        extract_resume_text,
        is_supported_upload_filename,
    )

    files = request.FILES.getlist("files")
    source_url = request.POST.get("source_url")
    if not files:
        return JsonResponse({"detail": "no files uploaded"}, status=400)

    results = []
    for file in files:
        filename = file.name
        if not is_supported_upload_filename(filename):
            results.append({
                "file_name": filename,
                "status": "skipped",
                "reason": "unsupported format (use PDF, Word, or ZIP)",
            })
            continue
        try:
            contents = file.read()
            entries = expand_upload(filename, contents)
            if not entries:
                results.append({"file_name": filename, "status": "skipped", "reason": "no resumes found"})
                continue
            for entry_name, entry_bytes in entries:
                try:
                    raw_text = extract_resume_text(entry_name, entry_bytes).strip()
                    if not raw_text:
                        results.append({"file_name": entry_name, "status": "error", "reason": "no text extracted"})
                        continue
                    processed = process_resume_text(
                        raw_text=raw_text, source_url=source_url, file_name=entry_name
                    )
                    parsed = processed.get("parsed", {})
                    results.append(
                        {
                            "file_name": entry_name,
                            "status": "ok",
                            "resume_id": processed.get("resume_id"),
                            "candidate_name": parsed.get("candidate_name"),
                            "current_title": parsed.get("current_title"),
                        }
                    )
                except Exception as e:
                    results.append({"file_name": entry_name, "status": "error", "reason": str(e)})
        except Exception as e:
            results.append({"file_name": filename, "status": "error", "reason": str(e)})

    return JsonResponse({"count": len(results), "items": results})


@csrf_exempt
@require_POST
def get_top_matches_by_role(request):
    from ranker_agent import get_top_matches_for_role

    role_name = request.POST.get("role_name")
    top_k = int(request.POST.get("top_k", 3))
    if not role_name:
        return JsonResponse({"detail": "role_name required"}, status=400)
    try:
        matches = get_top_matches_for_role(role_name=role_name, top_k=top_k)
    except Exception as e:
        return JsonResponse({"detail": str(e)}, status=500)
    return JsonResponse({"role_name": role_name, "top_k": top_k, "matches": matches})
