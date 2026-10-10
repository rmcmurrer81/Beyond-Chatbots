"""Inactive, deterministic body feedback boundary. No native IO or actuation.

This routes externally observed sensor packets for one separately owned body.
It does not model biological nerves, infer forces from geometry, or establish
subjective sensation. Native/calibrated sensor producers require separate review.
"""
from dataclasses import dataclass
import math
from types import MappingProxyType


@dataclass(frozen=True)
class BodyBinding:
    subject_id: str
    model_owner_id: str
    body_instance_id: str
    rig_sha256: str
    interface_revision: str


@dataclass(frozen=True)
class SensorRoute:
    sensor_id: str
    region: str
    modality: str
    unit: str
    frame_id: str
    clock_id: str
    producer_sha256: str
    calibration_sha256: str
    measurement_kind: str
    minimum: float
    maximum: float


@dataclass(frozen=True)
class SensorPacket:
    binding: BodyBinding
    sensor_id: str
    sequence: int
    monotonic_ns: int
    frame_id: str
    clock_id: str
    producer_sha256: str
    calibration_sha256: str
    measurement_kind: str
    status: str
    value: float | bool | None
    unit: str
    uncertainty: float | None
    error: str | None


@dataclass(frozen=True)
class FeedbackEvent:
    binding: BodyBinding
    sensor_id: str
    sequence: int
    monotonic_ns: int
    region: str
    modality: str
    unit: str
    frame_id: str
    clock_id: str
    producer_sha256: str
    calibration_sha256: str
    measurement_kind: str
    status: str
    value: float | bool | None
    uncertainty: float | None
    error: str | None
    subjective_sensation_verified: bool = False


@dataclass(frozen=True)
class MotorRequest:
    binding: BodyBinding
    request_id: str
    joint_id: str
    requested_angle_rad: float
    sequence: int
    monotonic_ns: int
    clock_id: str


def _label(value):
    return type(value) is str and 0 < len(value) <= 128 and all(ord(c) >= 32 for c in value)


def _digest(value):
    return type(value) is str and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


class FeedbackRefused(ValueError):
    """The caller must preserve the refused original packet with this reason."""


class InactiveBodyNerveNetwork:
    """One body, explicit routes, complete bounded event history, no actuator.

    A route is a nomination supplied by the body sensor producer. Registration
    alone does not authenticate its physics or calibration. A reviewed producer
    must supply measured values; geometric channels remain geometric evidence.
    """
    MODALITIES = {
        'contact': ('bool', {'collision_observation', 'contact_sensor'}),
        'joint_angle': ('rad', {'kinematic_observation', 'joint_encoder'}),
        'surface_displacement': ('m', {'kinematic_observation'}),
        'force': ('N', {'force_sensor', 'qualified_body_physics'}),
        'pressure': ('Pa', {'pressure_sensor', 'qualified_body_physics'}),
        'temperature': ('K', {'temperature_sensor', 'qualified_thermal_model'}),
    }

    def __init__(self, binding, routes, *, event_limit=512):
        if type(binding) is not BodyBinding or not all(_label(getattr(binding, k)) for k in ('subject_id', 'model_owner_id', 'body_instance_id', 'interface_revision')) or not _digest(binding.rig_sha256):
            raise FeedbackRefused('invalid body identity binding')
        if type(event_limit) is not int or not 1 <= event_limit <= 4096:
            raise FeedbackRefused('finite event history limit required')
        if type(routes) not in (list, tuple) or not 1 <= len(routes) <= 1024:
            raise FeedbackRefused('finite nonempty sensor routes required')
        table = {}
        for route in routes:
            if type(route) is not SensorRoute or not all(_label(getattr(route, k)) for k in ('sensor_id', 'region', 'frame_id', 'clock_id')):
                raise FeedbackRefused('invalid sensor route identity')
            if route.sensor_id in table or route.modality not in self.MODALITIES:
                raise FeedbackRefused('duplicate sensor or unsupported modality')
            unit, kinds = self.MODALITIES[route.modality]
            if route.unit != unit or route.measurement_kind not in kinds:
                raise FeedbackRefused('unit or measurement provenance incompatible with modality')
            if not _digest(route.producer_sha256) or not _digest(route.calibration_sha256) or not _number(route.minimum) or not _number(route.maximum) or route.minimum > route.maximum:
                raise FeedbackRefused('producer/calibration pin and finite range required')
            if route.modality == 'contact' and (route.minimum, route.maximum) != (0, 1):
                raise FeedbackRefused('contact uses the boolean domain')
            if route.modality in ('pressure', 'temperature') and route.minimum < 0:
                raise FeedbackRefused('pressure and absolute temperature cannot have negative ranges')
            table[route.sensor_id] = route
        self._binding = binding
        self._routes = MappingProxyType(table)
        self.event_limit = event_limit
        self._events = []
        self.last = {}
        self.disconnected = set()
        self._motor_requests = []
        self.motor_limits = {}
        self.motor_last = None

    @property
    def binding(self):
        return self._binding

    @property
    def routes(self):
        return self._routes

    @property
    def events(self):
        return tuple(self._events)

    @property
    def motor_requests(self):
        return tuple(self._motor_requests)

    def disconnect(self, sensor_id):
        if sensor_id not in self.routes:
            raise FeedbackRefused('unknown sensor connection')
        self.disconnected.add(sensor_id)

    def receive(self, packet):
        if type(packet) is not SensorPacket or packet.binding != self.binding:
            raise FeedbackRefused('body/model/subject/rig/interface identity mismatch')
        route = self.routes.get(packet.sensor_id)
        if route is None or packet.sensor_id in self.disconnected:
            raise FeedbackRefused('unknown or disconnected sensor')
        for field in ('frame_id', 'clock_id', 'producer_sha256', 'calibration_sha256', 'measurement_kind', 'unit'):
            if getattr(packet, field) != getattr(route, field):
                raise FeedbackRefused('sensor ' + field + ' mismatch')
        if type(packet.sequence) is not int or packet.sequence < 0 or type(packet.monotonic_ns) is not int or packet.monotonic_ns < 0:
            raise FeedbackRefused('nonnegative integer sequence and monotonic time required')
        previous = self.last.get(packet.sensor_id)
        if previous is not None and (packet.sequence <= previous[0] or packet.monotonic_ns <= previous[1]):
            raise FeedbackRefused('duplicate, stale, or reversed sensor packet')
        if packet.status not in ('observed', 'unknown', 'error'):
            raise FeedbackRefused('sham, request, or unsupported packet status')
        if packet.status == 'observed':
            if packet.error is not None or not _number(packet.uncertainty) or packet.uncertainty < 0:
                raise FeedbackRefused('observed value requires explicit finite uncertainty and no error')
            if route.modality == 'contact':
                if type(packet.value) is not bool or packet.uncertainty != 0:
                    raise FeedbackRefused('contact is an explicit boolean observation')
            elif not _number(packet.value) or not route.minimum <= packet.value <= route.maximum:
                raise FeedbackRefused('observed value outside declared calibrated range')
        elif packet.value is not None or packet.uncertainty is not None or (packet.status == 'error' and not _label(packet.error)) or (packet.status == 'unknown' and packet.error is not None):
            raise FeedbackRefused('unknown/error channels cannot contain invented measurements')
        if len(self.events) >= self.event_limit:
            raise FeedbackRefused('full event history retained; finite limit exhausted')
        event = FeedbackEvent(packet.binding, packet.sensor_id, packet.sequence, packet.monotonic_ns, route.region, route.modality, packet.unit, packet.frame_id, packet.clock_id, packet.producer_sha256, packet.calibration_sha256, packet.measurement_kind, packet.status, packet.value, packet.uncertainty, packet.error)
        self._events.append(event)
        self.last[packet.sensor_id] = (packet.sequence, packet.monotonic_ns)
        return event

    def configure_motor_limits(self, joint_limits):
        if self.motor_requests or self.motor_limits or type(joint_limits) is not dict or not 1 <= len(joint_limits) <= 163:
            raise FeedbackRefused('single fresh finite motor nomination required')
        for joint, bounds in joint_limits.items():
            if not _label(joint) or type(bounds) not in (tuple, list) or len(bounds) != 2 or not all(_number(x) for x in bounds) or bounds[0] > bounds[1]:
                raise FeedbackRefused('joint limits need finite radian bounds')
        self.motor_limits = {key: tuple(value) for key, value in joint_limits.items()}

    def record_motor_request(self, request):
        if type(request) is not MotorRequest or request.binding != self.binding or not _label(request.request_id) or not _label(request.clock_id):
            raise FeedbackRefused('motor request identity mismatch')
        bounds = self.motor_limits.get(request.joint_id)
        if bounds is None or not _number(request.requested_angle_rad) or not bounds[0] <= request.requested_angle_rad <= bounds[1]:
            raise FeedbackRefused('motor request outside nominated joint limit')
        if type(request.sequence) is not int or request.sequence < 0 or type(request.monotonic_ns) is not int or request.monotonic_ns < 0:
            raise FeedbackRefused('motor sequence/time invalid')
        if self.motor_last is not None and (request.clock_id != self.motor_last[2] or request.sequence <= self.motor_last[0] or request.monotonic_ns <= self.motor_last[1]):
            raise FeedbackRefused('motor clock changed or request stale')
        if len(self.motor_requests) >= self.event_limit or any(r.request_id == request.request_id for r in self.motor_requests):
            raise FeedbackRefused('motor history full or request ID reused')
        self._motor_requests.append(request)
        self.motor_last = (request.sequence, request.monotonic_ns, request.clock_id)
        return dict(request_id=request.request_id, status='REQUEST_RECORDED_WITHOUT_ACTUATION', movement_observed=False, subjective_sensation_verified=False)


@dataclass(frozen=True)
class QualificationReceipt:
    binding: BodyBinding
    stage: str
    review_sha256: str
    observations_sha256: str
    original_return_sha256: str
    observed_normal_return: bool
    independently_reviewed: bool
    accepted: bool
    sequence: int


class BodyQualificationOrder:
    """Retain external actual reviews and enforce the owner's test order.

    Receipt strings require separately authenticated full physical originals.
    This nomination boundary cannot replace source/native/actual review.
    """
    PREREQUISITES = {
        'rest_persistence': (),
        'basis_equivalence': ('rest_persistence',),
        'blink': ('basis_equivalence',),
        'breathing': ('basis_equivalence',),
        'stretch': ('blink', 'breathing'),
        'finger_movement': ('blink', 'breathing'),
    }

    def __init__(self, binding):
        if type(binding) is not BodyBinding:
            raise FeedbackRefused('qualification body binding required')
        self.binding = binding
        self._receipts = []

    @property
    def receipts(self):
        return tuple(self._receipts)

    def _current_qualified(self, stage, latest):
        result = latest.get(stage)
        if result is None or not result.accepted or not result.observed_normal_return or not result.independently_reviewed:
            return False
        for prerequisite in self.PREREQUISITES[stage]:
            if not self._current_qualified(prerequisite, latest) or result.sequence <= latest[prerequisite].sequence:
                return False
        return True

    def is_current_qualified(self, stage):
        if stage not in self.PREREQUISITES:
            raise FeedbackRefused('unknown qualification stage')
        return self._current_qualified(stage, {r.stage: r for r in self._receipts})

    def retain_reviewed_result(self, receipt):
        if type(receipt) is not QualificationReceipt or receipt.binding != self.binding or receipt.stage not in self.PREREQUISITES:
            raise FeedbackRefused('qualification identity or stage mismatch')
        if not all(_digest(getattr(receipt, k)) for k in ('review_sha256', 'observations_sha256', 'original_return_sha256')) or any(type(getattr(receipt, k)) is not bool for k in ('observed_normal_return', 'independently_reviewed', 'accepted')):
            raise FeedbackRefused('full review/observation/original-return commitments required')
        if type(receipt.sequence) is not int or receipt.sequence < 0 or self._receipts and receipt.sequence <= self._receipts[-1].sequence:
            raise FeedbackRefused('qualification sequence must progress')
        if len(self._receipts) >= 64:
            raise FeedbackRefused('complete qualification history limit exhausted')
        if receipt.accepted:
            if not receipt.observed_normal_return or not receipt.independently_reviewed:
                raise FeedbackRefused('unreviewed or failed original cannot qualify a stage')
            latest = {r.stage: r for r in self._receipts}
            for prerequisite in self.PREREQUISITES[receipt.stage]:
                if not self._current_qualified(prerequisite, latest) or receipt.sequence <= latest[prerequisite].sequence:
                    raise FeedbackRefused('earlier required body observation remains unqualified or stale')
        self._receipts.append(receipt)
        return receipt
