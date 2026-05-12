from rust_sensei.factory import ServiceFactory
from rust_sensei.services.assessment_service import AssessmentService
from rust_sensei.services.lesson_service import LessonService
from rust_sensei.services.progress_service import ProgressService
from rust_sensei.services.session_service import SessionService
from rust_sensei.services.setup_service import SetupService


def test_service_factory_creates_services(tmp_path):
    factory = ServiceFactory(state_dir=tmp_path)

    assert isinstance(factory.session_service(), SessionService)
    assert isinstance(factory.lesson_service(), LessonService)
    assert isinstance(factory.assessment_service(), AssessmentService)
    assert isinstance(factory.progress_service(), ProgressService)
    assert isinstance(factory.setup_service(), SetupService)
    assert (tmp_path / "logs").exists()
