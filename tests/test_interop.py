import json

import pytest
from sawyer_operations import Trajectory, export_table, import_table
from sawyer_operations.__main__ import main
from sawyer_operations.interop import (load_profile, read_table, resolve, save_profile,
                                       suggest_mapping, to_trajectory)

HEADERS = ['t'] + [f'q{joint}' for joint in range(7)] + [f'dq{joint}' for joint in range(7)]


def table(rows, *, headers=HEADERS, angle=10.0):
    lines = [','.join(headers)]
    for index in range(rows):
        values = [f'{index / 100:.2f}'] + [str(angle)] * 7 + ['0'] * 7
        lines.append(','.join(values))
    return '\n'.join(lines) + '\n'


def write(tmp_path, text, name='motion.csv'):
    path = tmp_path / name
    path.write_text(text)
    return path


def test_aliases_map_columns_and_degrees_convert(tmp_path):
    trajectory = import_table(write(tmp_path, table(3)), mode='position', units='deg')
    assert trajectory.rate_hz == 100.0 and len(trajectory.samples) == 3
    assert trajectory.samples[0].position.values[0] == pytest.approx(0.17453292)
    assert trajectory.duration_s == pytest.approx(0.03)
    headers, _ = read_table(write(tmp_path, table(2), 'again.csv'))
    assert suggest_mapping(headers, ('position', 'velocity')) == {
        'position': list(range(1, 8)), 'velocity': list(range(8, 15))}


def test_time_column_is_ignored_and_rate_is_assumed(tmp_path):
    text = table(3).replace('0.00', '17.5').replace('0.01', '99.0')
    assert import_table(write(tmp_path, text), mode='position', units='deg').rate_hz == 100.0


def test_position_limits_reject_unconverted_degrees(tmp_path):
    with pytest.raises(ValueError, match='outside its limit'):
        import_table(write(tmp_path, table(2, angle=95.0)), mode='position', units='rad')
    import_table(write(tmp_path, table(2, angle=95.0), 'ok.csv'), mode='position', units='deg')


def test_mode_requires_its_fields_and_nothing_is_derived(tmp_path):
    path = write(tmp_path, table(2))
    with pytest.raises(ValueError, match='No column matched'):
        import_table(path, mode='trajectory', units='deg')   # no acceleration columns
    velocity = import_table(path, mode='velocity', units='deg')
    assert velocity.mode.value == 'velocity'
    assert all(sample.position is None for sample in velocity.samples)
    position = import_table(path, mode='position', units='deg')
    assert all(sample.velocity is None for sample in position.samples)


def test_headerless_and_semicolon_tables(tmp_path):
    rows = ','.join(['0.0'] + ['0.1'] * 7) + '\n'
    headers, data = read_table(write(tmp_path, rows, 'bare.csv'))
    assert headers is None and len(data[0]) == 8
    trajectory = to_trajectory(data, {'position': list(range(1, 8))},
                               name='bare', mode='position', units='rad')
    assert trajectory.samples[0].position.values == (0.1,) * 7
    european = ';'.join(['0,00'] + ['1,5'] * 7) + '\n'
    _, decimal = read_table(write(tmp_path, european, 'euro.csv'))
    assert decimal[0][1] == '1.5'


def test_profile_round_trip(tmp_path):
    headers, rows = read_table(write(tmp_path, table(2)))
    mapping = {'position': list(range(1, 8))}
    save_profile(tmp_path / 'colleague.json', mode='position', units='deg',
                 mapping=mapping, headers=headers)
    profile = load_profile(tmp_path / 'colleague.json')
    assert profile['units'] == 'deg'
    shuffled = [headers[0]] + headers[8:] + headers[1:8]
    assert resolve(profile, shuffled) == {'position': list(range(8, 15))}
    with pytest.raises(ValueError, match='missing column'):
        resolve(profile, ['t', 'a', 'b'])


def test_export_round_trips_through_import(tmp_path):
    trajectory = import_table(write(tmp_path, table(4)), mode='position', units='deg')
    export_table(trajectory, tmp_path / 'out.csv', units='deg')
    again = import_table(tmp_path / 'out.csv', mode='position', units='deg', name=trajectory.name)
    assert again.to_dict() == trajectory.to_dict()
    with pytest.raises(FileExistsError):
        export_table(trajectory, tmp_path / 'out.csv')


def test_cli_import_is_non_interactive_with_flags(tmp_path):
    source, output = write(tmp_path, table(3)), tmp_path / 'motion.json'
    code = main(['import', str(source), '-o', str(output), '--mode', 'position', '--auto',
                 '--units', 'deg', '--save-profile', str(tmp_path / 'p.json')])
    assert code == 0
    assert Trajectory.load(output).summary()['samples'] == 3
    assert json.loads((tmp_path / 'p.json').read_text())['columns']['position'][0] == 'q0'
    assert main(['import', str(source), '-o', str(output), '--mode', 'position', '--auto',
                 '--units', 'deg']) == 1   # never overwrites
    second = tmp_path / 'second.json'
    assert main(['import', str(source), '-o', str(second), '--profile', str(tmp_path / 'p.json')]) == 0
    assert Trajectory.load(second).to_dict()['samples'] == Trajectory.load(output).to_dict()['samples']


def test_one_based_headers_are_not_silently_offset(tmp_path):
    headers = ['t'] + [f'J_{joint}' for joint in range(1, 8)]
    text = table(2, headers=headers)
    trajectory = import_table(write(tmp_path, text, 'onebased.csv'), mode='position', units='deg')
    assert len(trajectory.samples) == 2
    read, _ = read_table(write(tmp_path, text, 'again2.csv'))
    assert suggest_mapping(read, ('position',)) == {'position': list(range(1, 8))}
