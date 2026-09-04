import asyncio
import os
import re
import tempfile
import flet as ft
# yt_dlp навмисно НЕ імпортується тут: на Android збірка може не мати
# сумісних колес для деяких його C-залежностей (brotli, pycryptodomex тощо).
# Якщо імпорт впаде тут, на верхньому рівні модуля, застосунок помре ще
# до створення першого віджета -> білий екран без жодного повідомлення.
# Тому імпортуємо лениво, всередині функцій, де вже є try/except.


def format_duration(seconds):
    if seconds is None:
        return "[LIVE]"
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        return "--:--"

    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    if hours:
        return f"[{hours}:{minutes:02d}:{seconds:02d}]"
    return f"[{minutes:02d}:{seconds:02d}]"


def clean_title(title):
    if not title:
        return "Невідома назва"
    return re.sub(r"\s+", " ", title).strip()


def get_default_download_dir():
    """
    Шукаємо реальну публічну папку "Завантаження" на Android.
    Якщо немає прав/доступу - надійно падаємо в папку самого застосунку
    (вона завжди доступна для запису без жодних дозволів).
    """
    android_downloads = "/storage/emulated/0/Download"
    try:
        if os.path.isdir(android_downloads) and os.access(android_downloads, os.W_OK):
            return android_downloads
    except Exception:
        pass

    app_storage = os.getenv("FLET_APP_STORAGE_DATA")
    if app_storage:
        music_dir = os.path.join(app_storage, "Music")
        try:
            os.makedirs(music_dir, exist_ok=True)
            return music_dir
        except Exception:
            pass

    return tempfile.gettempdir()


async def main(page: ft.Page):
    # Захист від білого екрану: глобальний відлов помилок UI
    try:
        page.title = "Music Downloader"
        page.theme_mode = ft.ThemeMode.LIGHT
        # Тепла кольорова гама застосунку (жовтогарячий/бурштиновий).
        page.theme = ft.Theme(color_scheme_seed=ft.colors.DEEP_ORANGE)
        page.bgcolor = ft.colors.ORANGE_50
        page.padding = 10

        selected_folder = get_default_download_dir()
        search_results_data = []

        search_input = ft.TextField(
            hint_text="Введіть назву пісні або виконавця...",
            expand=True,
            text_size=16,
            content_padding=ft.padding.symmetric(horizontal=12, vertical=14),
            height=54,
        )

        limit_combo = ft.Dropdown(
            options=[
                ft.dropdown.Option("10"),
                ft.dropdown.Option("15"),
                ft.dropdown.Option("20"),
            ],
            value="10",
            width=80,
            height=54,
            content_padding=ft.padding.symmetric(horizontal=10, vertical=14),
        )

        # Кнопка пошуку - кругла іконка-лупа, тепла (жовтогаряча) барва,
        # стоїть в одному рядку разом із полем вводу і лічильником.
        search_button = ft.IconButton(
            icon=ft.icons.SEARCH,
            icon_color=ft.colors.WHITE,
            bgcolor=ft.colors.DEEP_ORANGE,
            icon_size=26,
            tooltip="Шукати",
        )

        results_list = ft.ListView(expand=True, spacing=6, padding=5)

        select_all_btn = ft.OutlinedButton("Все", expand=True)
        clear_btn = ft.OutlinedButton("Скинути", expand=True)

        # Кнопка завантаження - тепла барва, товща по вертикалі. Реальна
        # розтяжка на всю ширину задається нижче через
        # horizontal_alignment=STRETCH батьківського Column (сама кнопка,
        # якщо покласти окремим елементом Column без stretch, тягнеться
        # лише під розмір свого тексту - це і була причина "не на всю
        # ширину" минулого разу).
        download_btn = ft.ElevatedButton(
            "Завантажити обране",
            icon=ft.icons.DOWNLOAD,
            disabled=True,
            bgcolor=ft.colors.DEEP_ORANGE,
            color=ft.colors.WHITE,
            style=ft.ButtonStyle(padding=ft.padding.symmetric(vertical=22)),
        )

        status_label = ft.Text("Готовий до роботи", size=13)
        progress_bar = ft.ProgressBar(value=0, visible=True)

        async def set_busy(busy: bool):
            search_input.disabled = busy
            limit_combo.disabled = busy
            search_button.disabled = busy
            select_all_btn.disabled = busy
            clear_btn.disabled = busy
            download_btn.disabled = busy
            await page.update_async()

        def open_preview(url: str):
            # Замість вбудованого аудіо-плеєра (нестабільний на цій збірці
            # Android) відкриваємо трек у браузері/додатку YouTube - це
            # використовує вбудований, перевірений механізм ОС і не залежить
            # від крихкого аудіо-плагіна Flet.
            page.launch_url(url)

        async def start_search(e):
            query = search_input.value.strip()
            if not query:
                page.snack_bar = ft.SnackBar(ft.Text("Введіть назву треку!"))
                page.snack_bar.open = True
                await page.update_async()
                return

            await set_busy(True)
            results_list.controls.clear()
            search_results_data.clear()
            progress_bar.value = None
            status_label.value = f"Пошук: {query}..."
            await page.update_async()

            limit = int(limit_combo.value)
            loop = asyncio.get_running_loop()

            def _search_sync():
                import yt_dlp  # лінивий імпорт, помилка потрапить у except нижче
                search_query = f"ytsearch{limit}:{query} audio"
                ydl_opts = {
                    "extract_flat": True,
                    "skip_download": True,
                    "quiet": True,
                    "no_warnings": True,
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    return ydl.extract_info(search_query, download=False)

            try:
                data = await loop.run_in_executor(None, _search_sync)
                entries = data.get("entries") or []

                stop_words = [
                    "full movie", "повний фільм", "художній фільм",
                    "дивитися онлайн", "телемарафон", "єдині новини"
                ]

                for entry in entries:
                    if not entry:
                        continue

                    title = clean_title(entry.get("title"))
                    if any(w in title.lower() for w in stop_words):
                        continue

                    video_id = entry.get("id")
                    url = entry.get("url") or (
                        f"https://www.youtube.com/watch?v={video_id}" if video_id else None
                    )

                    if not url:
                        continue

                    channel = clean_title(
                        entry.get("channel") or entry.get("uploader") or "")
                    duration_str = format_duration(entry.get("duration"))
                    display_title = f"{channel} — {title}" if channel and not title.startswith(
                        channel) else title

                    search_results_data.append(
                        {"url": url, "title": display_title})

                    checkbox = ft.Checkbox(value=False)

                    title_text = ft.Text(
                        display_title,
                        size=13,
                        max_lines=2,
                        overflow=ft.TextOverflow.ELLIPSIS,
                    )
                    duration_text = ft.Text(
                        duration_str, size=11, color=ft.colors.GREY_600)

                    play_button = ft.IconButton(
                        icon=ft.icons.PLAY_ARROW,
                        tooltip="Відкрити на YouTube",
                        icon_size=22,
                    )

                    def make_play_handler(target_url):
                        def handler(e_click):
                            open_preview(target_url)
                        return handler

                    play_button.on_click = make_play_handler(url)

                    # Рядок результату: чекбокс + текст займають доступну
                    # ширину (expand=True), а кнопка програвання сидить у
                    # контейнері ФІКСОВАНОЇ ширини (48) праворуч - вона
                    # більше не може накладатись на текст назви.
                    row_item = ft.Container(
                        content=ft.Row(
                            controls=[
                                checkbox,
                                ft.Container(
                                    content=ft.Column(
                                        controls=[title_text, duration_text],
                                        spacing=2,
                                        tight=True,
                                    ),
                                    expand=True,
                                ),
                                ft.Container(content=play_button, width=48),
                            ],
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            spacing=4,
                        ),
                        padding=ft.padding.symmetric(vertical=2, horizontal=2),
                        border=ft.border.only(
                            bottom=ft.BorderSide(1, ft.colors.GREY_300)),
                    )

                    results_list.controls.append(row_item)

                if search_results_data:
                    status_label.value = f"Знайдено: {len(search_results_data)} треків."
                    download_btn.disabled = False
                else:
                    status_label.value = "Нічого не знайдено."
                    download_btn.disabled = True

            except Exception as exc:
                status_label.value = "Помилка пошуку"
                page.snack_bar = ft.SnackBar(ft.Text(f"Помилка: {exc}"))
                page.snack_bar.open = True

            progress_bar.value = 0
            await set_busy(False)

        search_button.on_click = start_search
        search_input.on_submit = start_search

        def _checkbox_of(container_row):
            return container_row.content.controls[0]

        async def select_all_click(e):
            for row in results_list.controls:
                _checkbox_of(row).value = True
            await page.update_async()

        async def clear_selection_click(e):
            for row in results_list.controls:
                _checkbox_of(row).value = False
            await page.update_async()

        select_all_btn.on_click = select_all_click
        clear_btn.on_click = clear_selection_click

        async def start_download(e):
            selected_urls = []
            for i, row in enumerate(results_list.controls):
                cb = _checkbox_of(row)
                if cb.value:
                    selected_urls.append(search_results_data[i]["url"])

            if not selected_urls:
                page.snack_bar = ft.SnackBar(
                    ft.Text("Виберіть хоча б один трек!"))
                page.snack_bar.open = True
                await page.update_async()
                return

            await set_busy(True)
            progress_bar.value = 0
            status_label.value = f"Завантаження: {len(selected_urls)} треків..."
            await page.update_async()

            loop = asyncio.get_running_loop()

            def _progress_hook(d):
                if d["status"] == "downloading":
                    total = d.get("total_bytes") or d.get(
                        "total_bytes_estimate") or 0
                    downloaded = d.get("downloaded_bytes") or 0
                    if total > 0:
                        percentage = downloaded / total
                        progress_bar.value = percentage
                        filename = os.path.basename(d.get("filename", ""))
                        status_label.value = f"Завантаження ({int(percentage * 100)}%): {filename}"
                        asyncio.run_coroutine_threadsafe(
                            page.update_async(), loop)

                elif d["status"] == "finished":
                    progress_bar.value = 1.0
                    status_label.value = "Збереження..."
                    asyncio.run_coroutine_threadsafe(page.update_async(), loop)

            def _download_sync():
                import yt_dlp  # лінивий імпорт, помилка потрапить у except нижче
                os.makedirs(selected_folder, exist_ok=True)
                ydl_opts = {
                    "format": "bestaudio[ext=m4a]/bestaudio/best",
                    "outtmpl": os.path.join(selected_folder, "%(title)s.%(ext)s"),
                    "progress_hooks": [_progress_hook],
                    "quiet": True,
                    "no_warnings": True,
                }
                saved_files = []
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    for single_url in selected_urls:
                        info = ydl.extract_info(single_url, download=True)
                        saved_files.append(ydl.prepare_filename(info))
                return saved_files

            try:
                saved_files = await loop.run_in_executor(None, _download_sync)
                existing = [f for f in saved_files if f and os.path.exists(f)]

                if len(existing) == len(selected_urls) and existing:
                    progress_bar.value = 1.0
                    status_label.value = f"Готово! Збережено {len(existing)} трек(ів)."
                    page.snack_bar = ft.SnackBar(
                        ft.Text(f"Збережено {len(existing)} трек(ів)."))
                    page.snack_bar.open = True
                elif existing:
                    status_label.value = f"Частково: {len(existing)} із {len(selected_urls)}."
                    page.snack_bar = ft.SnackBar(
                        ft.Text("Не всі треки вдалося зберегти."))
                    page.snack_bar.open = True
                else:
                    status_label.value = "Файли не збереглися."
                    page.snack_bar = ft.SnackBar(
                        ft.Text("Завантаження не вдалося зберегти на диск."))
                    page.snack_bar.open = True

            except Exception as exc:
                status_label.value = "Помилка завантаження"
                page.snack_bar = ft.SnackBar(ft.Text(f"Помилка: {exc}"))
                page.snack_bar.open = True

            await set_busy(False)

        download_btn.on_click = start_download

        # ---- ВЕРСТКА ----
        # Головний Column розтягнутий на всю сторінку (expand=True).
        # Всередині: верх (пошук) - фіксований; середина (результати) -
        # expand=True, займає ВСЕ вільне місце; низ (кнопки + статус) -
        # фіксований і притиснутий до низу екрана.
        page.add(
            ft.Column(
                controls=[
                    ft.Text("🎵 Music Downloader", size=18,
                            weight=ft.FontWeight.BOLD),

                    # Пошук - поле вводу, лічильник і кнопка-лупа в одному
                    # рядку. Поле вводу забирає всю доступну ширину
                    # (expand=True), решта - фіксованого розміру.
                    ft.Row(controls=[search_input, limit_combo,
                           search_button], spacing=8),

                    # Результати пошуку - займають усе вільне місце.
                    ft.Container(
                        content=results_list,
                        expand=True,
                        border=ft.border.all(1, ft.colors.GREY_300),
                        border_radius=8,
                    ),

                    ft.Row(controls=[select_all_btn, clear_btn], spacing=8),
                    download_btn,

                    ft.Divider(),

                    # Статус - фіксований блок унизу екрана.
                    status_label,
                    progress_bar,
                ],
                spacing=10,
                expand=True,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            )
        )
    except Exception as main_err:
        page.add(
            ft.Text(f"Помилка запуску додатку: {main_err}", color="red", selectable=True))


if __name__ == "__main__":
    try:
        ft.app(target=main)
    except Exception as e:
        import traceback
        err_msg = traceback.format_exc()

        def error_view(page: ft.Page):
            page.add(
                ft.Text("Критична помилка при запуску:",
                        color="red", weight="bold"),
                ft.Text(err_msg, selectable=True)
            )
        ft.app(target=error_view)
