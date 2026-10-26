from spotifactory.tasks.base import Task
from spotifactory.tasks.film.steps import FilmCountStep


class FilmCountTask(Task):
    """Menu > Film Left: ask the Instax how many shots are left in the pack."""
    name = "film_count"
    steps = [
        ("check", FilmCountStep),
    ]
