from celery import Celery
from src.config.index import appConfig
from src.rag.ingestion.index import process_document

celery_app = Celery(
    "multi-modal-rag",  # Name of the Celery App
    broker=appConfig["redis_url"],  # broker - Redis Queue - Tasks are queued
)


@celery_app.task
def perform_rag_ingestion_task(document_id: str):
    try:
        process_document_result = process_document(document_id)
        return (
            f"Document {process_document_result['document_id']} processed successfully"
        )
    except Exception as e:
        return f"Failed to process document {document_id}: {str(e)}"


@celery_app.task(name="case_law.crawl")
def perform_case_law_crawl_task(
    job_id: str,
    linh_vuc: int = 34,
    max_pages: int = 5,
    max_items: int | None = None,
):
    from src.services.caseLawCrawlJobStore import update_crawl_job
    from src.services.caseLawCrawlerService import crawl_and_ingest_case_laws

    update_crawl_job(
        job_id,
        status="running",
        percent=1,
        message="Worker đã nhận job, bắt đầu crawl án lệ...",
        error=None,
    )

    try:
        return crawl_and_ingest_case_laws(
            linh_vuc=linh_vuc,
            max_pages=max_pages,
            max_items=max_items,
            job_id=job_id,
        )
    except Exception as error:
        update_crawl_job(
            job_id,
            status="failed",
            percent=100,
            message="Crawl án lệ thất bại",
            error=str(error),
        )
        raise
