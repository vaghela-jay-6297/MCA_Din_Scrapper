from django.core.management.base import BaseCommand
from django_celery_beat.models import PeriodicTask, CrontabSchedule
from django.db.utils import ProgrammingError, OperationalError
import logging
import time

logger = logging.getLogger('din_app')

class Command(BaseCommand):
    help = 'Set up Celery Beat schedule for cleanup_old_logs task'

    def handle(self, *args, **options):
        max_retries = 5
        retry_delay = 5  # seconds

        for attempt in range(max_retries):
            try:
                # Create or get schedule: run daily at midnight UTC
                schedule, _ = CrontabSchedule.objects.get_or_create(
                    minute='0',
                    hour='0',
                    day_of_week='*',
                    day_of_month='*',
                    month_of_year='*',
                    defaults={'timezone': 'UTC'}
                )

                # Create or update periodic task
                PeriodicTask.objects.update_or_create(
                    name='Cleanup old logs',
                    defaults={
                        'crontab': schedule,
                        'task': 'din_app.tasks.cleanup_old_logs',
                        'enabled': True,
                    }
                )
                logger.info('Successfully set up Celery Beat schedule for cleanup_old_logs')
                return

            except (ProgrammingError, OperationalError) as e:
                if attempt < max_retries - 1:
                    logger.warning(f"Database not ready (attempt {attempt + 1}/{max_retries}): {str(e)}. Retrying in {retry_delay} seconds.")
                    time.sleep(retry_delay)
                else:
                    logger.error(f"Failed to set up Celery Beat schedule after {max_retries} attempts: {str(e)}")
                    raise