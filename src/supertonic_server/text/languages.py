"""Supported languages and their metadata."""

from __future__ import annotations

from dataclasses import dataclass

from supertonic.config import SUPPORTED_LANGUAGES

from supertonic_server.core.errors import ApiError


@dataclass(frozen=True)
class Language:
    """A language the model can speak.

    Attributes:
        code: Model language code (``"na"`` means unknown / auto).
        name: English display name.
        sample: One short natural sentence, used for previews and UI samples.
        spaced: Whether words are separated by spaces.
    """

    code: str
    name: str
    sample: str
    spaced: bool = True


_META: dict[str, tuple[str, str]] = {
    "en": ("English", "The quick brown fox jumps over the lazy dog."),
    "ko": ("Korean", "안녕하세요, 오늘 날씨가 정말 좋네요."),
    "ja": ("Japanese", "こんにちは、今日はとても良い天気ですね。"),
    "ar": ("Arabic", "مرحباً، الطقس جميل جداً اليوم."),
    "bg": ("Bulgarian", "Здравейте, днес времето е наистина хубаво."),
    "cs": ("Czech", "Dobrý den, dnes je opravdu krásné počasí."),
    "da": ("Danish", "Goddag, vejret er virkelig dejligt i dag."),
    "de": ("German", "Guten Tag, das Wetter ist heute wirklich schön."),
    "el": ("Greek", "Γεια σας, ο καιρός είναι πραγματικά υπέροχος σήμερα."),
    "es": ("Spanish", "Hola, hoy hace un día realmente precioso."),
    "et": ("Estonian", "Tere, täna on tõesti ilus ilm."),
    "fi": ("Finnish", "Hei, tänään on todella kaunis sää."),
    "fr": ("French", "Bonjour, il fait vraiment beau aujourd'hui."),
    "hi": ("Hindi", "नमस्ते, आज मौसम सचमुच बहुत सुहावना है।"),
    "hr": ("Croatian", "Dobar dan, danas je stvarno lijepo vrijeme."),
    "hu": ("Hungarian", "Jó napot, ma tényleg gyönyörű idő van."),
    "id": ("Indonesian", "Halo, cuacanya benar-benar indah hari ini."),
    "it": ("Italian", "Buongiorno, oggi il tempo è davvero bellissimo."),
    "lt": ("Lithuanian", "Laba diena, šiandien tikrai graži diena."),
    "lv": ("Latvian", "Labdien, šodien ir patiešām jauks laiks."),
    "nl": ("Dutch", "Goedendag, het weer is vandaag echt prachtig."),
    "pl": ("Polish", "Dzień dobry, dziś jest naprawdę piękna pogoda."),
    "pt": ("Portuguese", "Olá, hoje o tempo está realmente lindo."),
    "ro": ("Romanian", "Bună ziua, astăzi vremea este cu adevărat frumoasă."),
    "ru": ("Russian", "Здравствуйте, сегодня действительно прекрасная погода."),
    "sk": ("Slovak", "Dobrý deň, dnes je naozaj krásne počasie."),
    "sl": ("Slovenian", "Dober dan, danes je res lepo vreme."),
    "sv": ("Swedish", "God dag, vädret är verkligen fint idag."),
    "tr": ("Turkish", "Merhaba, bugün hava gerçekten çok güzel."),
    "uk": ("Ukrainian", "Добрий день, сьогодні справді чудова погода."),
    "vi": ("Vietnamese", "Xin chào, hôm nay thời tiết thật đẹp."),
}

LANGUAGES: list[Language] = [
    Language(code, *_META[code], spaced=code != "ja") for code in SUPPORTED_LANGUAGES
] + [Language("na", "Unknown / auto", "Hello, this is a short sample of my voice.")]

_BY_CODE: dict[str, Language] = {lang.code: lang for lang in LANGUAGES}


def get_language(code: str) -> Language:
    """Return the language for ``code``.

    Raises:
        ApiError: 400 ``language_not_supported`` if the code is unknown.
    """
    try:
        return _BY_CODE[code]
    except KeyError:
        raise ApiError(
            400,
            "language_not_supported",
            f"Language {code!r} is not supported. Supported: {', '.join(_BY_CODE)}.",
            param="language",
        ) from None
