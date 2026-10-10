"""Synthetic boundary controls. No native body, subjective or physics acceptance."""
from dataclasses import replace, asdict
import hashlib
import json
from pathlib import Path
from body_nerve_feedback import BodyBinding, SensorRoute, SensorPacket, MotorRequest, InactiveBodyNerveNetwork, FeedbackRefused, BodyQualificationOrder, QualificationReceipt

HERE = Path(__file__).resolve().parent
binding = BodyBinding('fixture-subject', 'fixture-model-owner', 'fixture-body-instance', 'a' * 64, 'inactive-feedback-v1')
contact = SensorRoute('left-index-contact', 'left-index-fingertip', 'contact', 'bool', 'body-local', 'fixture-clock', 'b' * 64, 'c' * 64, 'collision_observation', 0, 1)
force = SensorRoute('left-index-force', 'left-index-fingertip', 'force', 'N', 'body-local', 'fixture-clock', 'd' * 64, 'e' * 64, 'force_sensor', 0, 100)
network = InactiveBodyNerveNetwork(binding, [contact, force], event_limit=16)
checks = []

def refused(label, callable_):
    try:
        callable_()
    except FeedbackRefused as error:
        checks.append(dict(control=label, refusal=str(error)))
        return
    raise AssertionError(label + ' was accepted')

no_contact = SensorPacket(binding, contact.sensor_id, 0, 1000, contact.frame_id, contact.clock_id, contact.producer_sha256, contact.calibration_sha256, contact.measurement_kind, 'observed', False, 'bool', 0, None)
no_contact_event = network.receive(no_contact)
assert no_contact_event.value is False and no_contact_event.subjective_sensation_verified is False
unknown_force = SensorPacket(binding, force.sensor_id, 0, 1000, force.frame_id, force.clock_id, force.producer_sha256, force.calibration_sha256, force.measurement_kind, 'unknown', None, 'N', None, None)
unknown_force_event = network.receive(unknown_force)
assert unknown_force_event.value is None and unknown_force_event.status == 'unknown'
refused('geometry cannot register as a force producer', lambda: InactiveBodyNerveNetwork(binding, [replace(force, measurement_kind='kinematic_observation')]))
for field, value in [('subject_id', 'other-subject'), ('model_owner_id', 'other-owner'), ('body_instance_id', 'other-body'), ('rig_sha256', 'f' * 64), ('interface_revision', 'other-interface')]:
    refused('identity mismatch ' + field, lambda field=field, value=value: network.receive(replace(no_contact, binding=replace(binding, **{field: value}), sequence=1, monotonic_ns=2000)))
for field, value in [('frame_id', 'world'), ('clock_id', 'other-clock'), ('producer_sha256', 'f' * 64), ('calibration_sha256', 'f' * 64), ('measurement_kind', 'contact_sensor'), ('unit', 'N')]:
    refused('sensor mismatch ' + field, lambda field=field, value=value: network.receive(replace(no_contact, **{field: value}, sequence=1, monotonic_ns=2000)))
refused('sham packet', lambda: network.receive(replace(no_contact, status='sham', sequence=1, monotonic_ns=2000)))
refused('duplicate original packet', lambda: network.receive(no_contact))
refused('reversed clock', lambda: network.receive(replace(no_contact, sequence=1, monotonic_ns=999)))
refused('invented unknown value', lambda: network.receive(replace(unknown_force, sequence=1, monotonic_ns=2000, value=0)))
network.disconnect(contact.sensor_id)
refused('disconnected nerve route', lambda: network.receive(replace(no_contact, sequence=1, monotonic_ns=2000)))
network.configure_motor_limits({'finger2-1.L': (0, .5)})
request = MotorRequest(binding, 'finger-request-1', 'finger2-1.L', .2, 0, 2000, 'fixture-clock')
request_receipt = network.record_motor_request(request)
assert request_receipt['movement_observed'] is False and len(network.events) == 2
refused('motor beyond nominated limits', lambda: network.record_motor_request(replace(request, request_id='finger-request-2', requested_angle_rad=1, sequence=1, monotonic_ns=3000)))
refused('motor request ID reuse', lambda: network.record_motor_request(replace(request, sequence=1, monotonic_ns=3000)))
order = BodyQualificationOrder(binding)
def result(stage, sequence, accepted=True):
    return QualificationReceipt(binding, stage, '1' * 64, '2' * 64, '3' * 64, True, True, accepted, sequence)
refused('fingers before blinking and breathing', lambda: order.retain_reviewed_result(result('finger_movement', 0)))
refused('stretch before blinking and breathing', lambda: order.retain_reviewed_result(result('stretch', 0)))
for sequence, stage in enumerate(('rest_persistence', 'basis_equivalence', 'blink')):
    order.retain_reviewed_result(result(stage, sequence))
refused('fingers while breathing remains pending', lambda: order.retain_reviewed_result(result('finger_movement', 3)))
order.retain_reviewed_result(result('breathing', 3))
order.retain_reviewed_result(result('stretch', 4))
order.retain_reviewed_result(result('finger_movement', 5))
order.retain_reviewed_result(result('breathing', 6, accepted=False))
refused('later breathing failure removes current progression', lambda: order.retain_reviewed_result(result('finger_movement', 7)))
# Transitive epoch controls: a fresh upstream result invalidates older children.
epoch = BodyQualificationOrder(binding)
for sequence, stage in enumerate(('rest_persistence', 'basis_equivalence', 'blink', 'breathing', 'stretch', 'finger_movement')):
    epoch.retain_reviewed_result(result(stage, sequence))
assert all(epoch.is_current_qualified(stage) for stage in epoch.PREREQUISITES)
epoch.retain_reviewed_result(result('rest_persistence', 6, accepted=False))
assert not any(epoch.is_current_qualified(stage) for stage in epoch.PREREQUISITES)
refused('failed rest invalidates transitive stretch', lambda: epoch.retain_reviewed_result(result('stretch', 7)))
refused('failed rest invalidates transitive fingers', lambda: epoch.retain_reviewed_result(result('finger_movement', 7)))
epoch.retain_reviewed_result(result('rest_persistence', 7))
assert epoch.is_current_qualified('rest_persistence') and not epoch.is_current_qualified('basis_equivalence')
refused('reaccepted rest cannot reuse old blink/breath', lambda: epoch.retain_reviewed_result(result('stretch', 8)))
epoch.retain_reviewed_result(result('basis_equivalence', 8))
assert epoch.is_current_qualified('basis_equivalence') and not epoch.is_current_qualified('blink') and not epoch.is_current_qualified('breathing')
refused('fresh basis cannot reuse older blink/breath', lambda: epoch.retain_reviewed_result(result('finger_movement', 9)))
epoch.retain_reviewed_result(result('blink', 9))
refused('new blink cannot reuse old breathing', lambda: epoch.retain_reviewed_result(result('stretch', 10)))
epoch.retain_reviewed_result(result('breathing', 10))
epoch.retain_reviewed_result(result('stretch', 11))
epoch.retain_reviewed_result(result('finger_movement', 12))
assert epoch.is_current_qualified('stretch') and epoch.is_current_qualified('finger_movement')
epoch.retain_reviewed_result(result('basis_equivalence', 13, accepted=False))
assert not epoch.is_current_qualified('blink') and not epoch.is_current_qualified('breathing') and not epoch.is_current_qualified('stretch') and not epoch.is_current_qualified('finger_movement')
refused('failed basis invalidates transitive fingers', lambda: epoch.retain_reviewed_result(result('finger_movement', 14)))
epoch.retain_reviewed_result(result('basis_equivalence', 14))
refused('reaccepted basis requires fresh blink/breath', lambda: epoch.retain_reviewed_result(result('stretch', 15)))
epoch.retain_reviewed_result(result('blink', 15))
epoch.retain_reviewed_result(result('breathing', 16))
epoch.retain_reviewed_result(result('stretch', 17))
epoch.retain_reviewed_result(result('finger_movement', 18))
assert epoch.is_current_qualified('stretch') and epoch.is_current_qualified('finger_movement')
epoch.retain_reviewed_result(result('blink', 19))
assert not epoch.is_current_qualified('stretch') and not epoch.is_current_qualified('finger_movement')
refused('old downstream receipt cannot replay into fresh epoch', lambda: epoch.retain_reviewed_result(result('stretch', 17)))

output = dict(schema='avatar231.inactive-nerve-feedback-synthetic-controls.v1', source=dict(bytes=(HERE / 'body_nerve_feedback.py').stat().st_size, sha256=hashlib.sha256((HERE / 'body_nerve_feedback.py').read_bytes()).hexdigest()), fixture_binding=asdict(binding), no_contact_event=asdict(no_contact_event), unknown_force_event=asdict(unknown_force_event), request_receipt=request_receipt, refused_controls=checks, retained_feedback_events=len(network.events), retained_qualification_reviews=len(order.receipts), retained_epoch_reviews=len(epoch.receipts), transitive_freshness_controls=True, native_calls=0, biological_nerve_model_implemented=False, pressure_or_force_inferred_from_geometry=False, subjective_sensation_verified=False, runtime_authority=False, full_body_ready=False)
data = json.dumps(output, ensure_ascii=True, sort_keys=True, indent=2).encode()
with (HERE / 'NERVE-CONTROLS.private.json').open('xb') as stream:
    assert stream.write(data) == len(data)
assert (HERE / 'NERVE-CONTROLS.private.json').read_bytes() == data
print(json.dumps(dict(controls=len(checks), product_sha256=hashlib.sha256(data).hexdigest(), native_calls=0, runtime_authority=False)))
