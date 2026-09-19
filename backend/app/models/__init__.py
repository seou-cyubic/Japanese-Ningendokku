"""SQLAlchemy 모델 패키지.

여기서 전 모델을 한 번씩 import 한다.

SQLAlchemy 는 `relationship("Hospital")` 처럼 **문자열로 적은 관계**를
매퍼 설정 시점에 이름으로 찾는다. 그 클래스가 아직 import 되지 않았으면

    InvalidRequestError: expression 'Hospital' failed to locate a name

로 죽는다. 어떤 모듈을 먼저 import 하느냐에 따라 되기도 하고 안 되기도 하는
문제라 원인을 찾기 어렵다. 이 파일이 그 순서 문제를 없앤다.
"""

from app.models.admin import AdminUser, AuditLog
from app.models.exam_option import ExamOption
from app.models.hospital import Hospital, HospitalSchedule, ReservationCount
from app.models.lookup_attempt import LookupAttempt
from app.models.mail import MailLog, MailTemplate
from app.models.postal_code import PostalCode
from app.models.reservation import ContactHistory, Reservation, ReservationOption
from app.models.target_person import TargetPerson

__all__ = [
    "AdminUser",
    "AuditLog",
    "ContactHistory",
    "ExamOption",
    "Hospital",
    "HospitalSchedule",
    "LookupAttempt",
    "MailLog",
    "MailTemplate",
    "PostalCode",
    "Reservation",
    "ReservationCount",
    "ReservationOption",
    "TargetPerson",
]
