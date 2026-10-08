"""Strict SI input contract; provenance is an assertion, not verified evidence."""
import math

FIELDS = {
    'length_1_m': (0.05, 0.5), 'length_2_m': (0.05, 0.5),
    'width_m': (0.01, 0.08), 'thickness_m': (0.005, 0.04),
    'density_kg_m3': (100, 20000), 'payload_kg': (0.001, 5),
    'payload_radius_m': (0.005, 0.04), 'torque_limit_nm': (0.01, 100),
    'reach_min_m': (0.1, 1), 'mass_max_kg': (0.01, 30),
    'uncertainty_fraction': (0, 0.25),
}
UNITS = {k: ('kg/m3' if k == 'density_kg_m3' else 'N*m' if k == 'torque_limit_nm'
             else 'kg' if k.endswith('_kg') else '1' if k == 'uncertainty_fraction' else 'm') for k in FIELDS}


def validate(raw):
    if not isinstance(raw, dict) or set(raw) != {'schema_version', 'example_only', 'reviewed', 'measurements'}:
        raise ValueError('Expected schema_version, example_only, reviewed, measurements only')
    if type(raw['schema_version']) is not int or raw['schema_version'] != 1 or raw['reviewed'] is not True:
        raise ValueError('Schema 1 requires explicit reviewed=true')
    if type(raw['example_only']) is not bool:
        raise ValueError('example_only must be boolean')
    measurements = raw['measurements']
    if not isinstance(measurements, dict) or set(measurements) != set(FIELDS):
        raise ValueError('All defined measurements are required; unknown parameters rejected')
    values = {}
    for name, (low, high) in FIELDS.items():
        item = measurements[name]
        if not isinstance(item, dict) or set(item) != {'value', 'unit', 'source'}:
            raise ValueError(f'{name}: value, unit and source required')
        value = item['value']
        if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f'{name}: finite value in [{low}, {high}] required')
        if item['unit'] != UNITS[name] or not isinstance(item['source'], str) or not item['source'].strip():
            raise ValueError(f'{name}: exact SI unit {UNITS[name]} and nonempty source required')
        values[name] = float(value)
    if values['payload_radius_m'] >= values['length_2_m'] / 2:
        raise ValueError('Payload radius must be smaller than half link 2')
    return values


def masses(p):
    return [p[f'length_{i}_m'] * p['width_m'] * p['thickness_m'] * p['density_kg_m3'] for i in (1, 2)]


def cheap_checks(p):
    mass = sum(masses(p)) + p['payload_kg']
    reach = p['length_1_m'] + p['length_2_m']
    # Conservative horizontal static load under upper mass/density uncertainty.
    m1, m2 = masses(p)
    a, b = p['length_1_m'], p['length_2_m']
    torque = 9.81 * (m1*a/2 + m2*(a+b/2) + p['payload_kg']*(a+b)) * (1+p['uncertainty_fraction'])
    violations = []
    worst_mass = mass * (1+p['uncertainty_fraction'])
    if worst_mass > p['mass_max_kg']: violations.append('mass_limit')
    if p['payload_radius_m'] >= p['length_2_m']/2: violations.append('payload_geometry')
    if reach < p['reach_min_m']: violations.append('reach_minimum')
    if torque > p['torque_limit_nm']: violations.append('static_torque_limit')
    return {'status': 'failed' if violations else 'passed', 'violations': violations,
            'mass_kg': mass, 'worst_mass_kg':worst_mass, 'reach_m': reach, 'worst_static_torque_nm': torque}
