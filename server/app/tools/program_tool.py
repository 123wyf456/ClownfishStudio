from app.schemas import RadioProgram
from app.tools.mock_data import read_mock_json

_SAVED_PROGRAMS: list[RadioProgram] | None = None


def save_program(program: RadioProgram) -> RadioProgram:
    _get_program_store().append(program)
    return program


def list_programs() -> list[RadioProgram]:
    return list(_get_program_store())


def get_program(program_id: str) -> RadioProgram | None:
    for program in _get_program_store():
        if program.program_id == program_id:
            return program

    return None


def _get_program_store() -> list[RadioProgram]:
    global _SAVED_PROGRAMS

    if _SAVED_PROGRAMS is None:
        data = read_mock_json("programs.json")
        programs = data["programs"]
        if not isinstance(programs, list):
            raise ValueError("program mock data is malformed")

        _SAVED_PROGRAMS = [
            RadioProgram.model_validate(program)
            for program in programs
            if isinstance(program, dict)
        ]

    return _SAVED_PROGRAMS
