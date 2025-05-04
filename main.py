import pygame
import sys
import time
import math

# --- Настройки ---
WIDTH, HEIGHT = 1000, 700
ZONE_CENTER = (350, 350)
ZONE_RADIUS = 180
ROD_SIZE = 38
ROD_GRID = 9  # 9x9 сетка, но не все стержни будут активны
ROD_TOTAL = 0  # будет посчитано

# --- Цвета ---
WHITE = (255, 255, 255)
GRAY = (180, 180, 180)
DARK_GRAY = (60, 60, 60)
RED = (200, 0, 0)
GREEN = (0, 180, 0)
BLUE = (0, 0, 200)
BLACK = (0, 0, 0)
YELLOW = (255, 255, 0)
ORANGE = (255, 120, 0)
LAMP_BG = (30, 20, 10)
LAMP_GLOW = (255, 120, 0)
LAMP_DIGIT = (255, 180, 60)
BUTTON_FACE = (180, 180, 200)
BUTTON_SHADOW = (100, 100, 120)
BUTTON_HIGHLIGHT = (220, 220, 255)

# --- Pygame init ---
pygame.init()
pygame.mixer.init()
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("РБМК-1000 Simulator")
font = pygame.font.SysFont(None, 24)
font_mono = pygame.font.SysFont("consolas", 48, bold=True)
font_lamp = pygame.font.SysFont("consolas", 64, bold=True)

# --- Звуки ---
az5_alarm_sound = pygame.mixer.Sound("sounds/alarm-az-5fast.ogg")
explosive_alarm_sound = pygame.mixer.Sound("sounds/alarm-explosive.ogg")
saor_alarm_sound = pygame.mixer.Sound("sounds/alarm-saor.ogg")
az5_alarm_channel = None
explosive_alarm_played = False

# --- Реакторные параметры ---
temperature = 20
sfkre = 0
last_update = time.time()
last_saor_time = 0
auto_protection_enabled = True
cooling_mode = 'normal'
exploded = False
last_az5_time = -10  # чтобы сразу можно было нажать

# --- Для механики прироста температуры от СФКРЭ ---
sfkre_temp_accum = 0

# --- Стержни ---
rods = []
rod_selected = []

# --- Глобальные переменные для АЗ-5 ---
az5_decay_active = False
az5_decay_target = 0

# --- Глобальные переменные для ключа питания муфт ---
muf_switch_active = False
muf_switch_decay_target = 0
muf_switch_last_time = 0

class Rod:
    def __init__(self, i, j, x, y):
        self.i = i
        self.j = j
        self.x = x
        self.y = y
        self.inserted = True
        self.raising = False
        self.raising_start_time = None
        self.fully_raised = False
        self.lowering = False
        self.lowering_start_time = None

    def rect(self):
        return pygame.Rect(self.x, self.y, ROD_SIZE, ROD_SIZE)

# --- Генерация скруглённой зоны ---
for i in range(ROD_GRID):
    for j in range(ROD_GRID):
        # Центр квадрата
        x = ZONE_CENTER[0] + (j - ROD_GRID // 2) * (ROD_SIZE + 4)
        y = ZONE_CENTER[1] + (i - ROD_GRID // 2) * (ROD_SIZE + 4)
        # Проверка, попадает ли в круг
        if (x - ZONE_CENTER[0]) ** 2 + (y - ZONE_CENTER[1]) ** 2 <= ZONE_RADIUS ** 2:
            rods.append(Rod(i, j, x, y))
ROD_TOTAL = len(rods)

# --- Кнопки ---
class Button:
    def __init__(self, x, y, w, h, text, color, callback):
        self.rect = pygame.Rect(x, y, w, h)
        self.text = text
        self.color = color
        self.callback = callback
        self.hovered = False

    def draw(self):
        # Тень
        shadow_rect = self.rect.move(4, 4)
        pygame.draw.rect(screen, BUTTON_SHADOW, shadow_rect, border_radius=10)
        # Лицевая часть
        face_color = BUTTON_HIGHLIGHT if self.hovered else self.color
        pygame.draw.rect(screen, face_color, self.rect, border_radius=10)
        pygame.draw.rect(screen, BLACK, self.rect, 2, border_radius=10)
        # Текст
        txt = font.render(self.text, True, BLACK)
        txt_rect = txt.get_rect(center=self.rect.center)
        screen.blit(txt, txt_rect)

    def handle_event(self, event):
        if event.type == pygame.MOUSEMOTION:
            self.hovered = self.rect.collidepoint(event.pos)
        if event.type == pygame.MOUSEBUTTONDOWN and self.rect.collidepoint(event.pos):
            self.callback()

buttons = []

# --- AZ-5 логика ---
az5_triggered = False
az5_cooldown = 0

def az5_action():
    global sfkre, temperature, az5_triggered, az5_cooldown, last_az5_time, az5_decay_active, az5_decay_target, exploded, az5_alarm_channel
    if exploded:
        return
    now = time.time()
    if now - last_az5_time < 5:
        return
    last_az5_time = now
    for rod in rods:
        rod.inserted = True
        rod.raising = False
        rod.raising_start_time = None
        rod.fully_raised = False
        rod.lowering = False
        rod.lowering_start_time = None
    if sfkre > 0:
        sfkre += 100
    temperature += 50
    az5_decay_active = True
    az5_decay_target = 0  # Можно сделать 0 или другой минимум
    # Воспроизвести звук АЗ-5
    if az5_alarm_channel is None or not az5_alarm_channel.get_busy():
        az5_alarm_channel = az5_alarm_sound.play(loops=-1)

def saor_action():
    global temperature, last_saor_time, exploded
    if exploded:
        return
    if time.time() - last_saor_time >= 60:
        temperature = max(20, temperature - 300)
        last_saor_time = time.time()
        # Воспроизвести звук САОР
        saor_alarm_sound.play()

def update_reactor():
    global sfkre, temperature, exploded, last_update, az5_triggered, az5_cooldown, az5_decay_active, az5_decay_target
    global muf_switch_active, muf_switch_decay_target
    global sfkre_temp_accum
    global az5_alarm_channel, explosive_alarm_played

    now = time.time()
    if now - last_update >= 1:
        last_update = now

        # Поднимающиеся стержни
        for rod in rods:
            if rod.raising and not rod.fully_raised:
                sfkre += 10
                if sfkre < 0:
                    sfkre = 0

        # Опускающиеся стержни
        for rod in rods:
            if rod.lowering:
                sfkre -= 10
                if sfkre < 0:
                    sfkre = 0

        # --- Плавное снижение СФКРЭ после АЗ-5 ---
        if az5_decay_active:
            if sfkre > az5_decay_target and sfkre > 0:
                sfkre -= 50
                if sfkre < az5_decay_target:
                    sfkre = az5_decay_target
            else:
                az5_decay_active = False

        # --- Плавное снижение СФКРЭ после MUF SWITCH ---
        if muf_switch_active:
            if sfkre > muf_switch_decay_target and sfkre > 0:
                sfkre -= 100  # Быстрее, чем у АЗ-5
                if sfkre < muf_switch_decay_target:
                    sfkre = muf_switch_decay_target
            else:
                muf_switch_active = False

        # --- Механика: каждые +25 к СФКРЭ дают +5 к температуре ---
        sfkre_delta = sfkre - sfkre_temp_accum
        if sfkre_delta > 0:
            add_temp = (sfkre_delta // 25) * 5
            if add_temp > 0:
                temperature += add_temp
                sfkre_temp_accum += (sfkre_delta // 25) * 25
        elif sfkre_delta < 0:
            # Если СФКРЭ уменьшилось, корректируем накопитель
            sfkre_temp_accum = sfkre

        # Завершение поднятия
        for rod in rods:
            if rod.raising and not rod.fully_raised:
                if now - rod.raising_start_time >= 5:
                    rod.raising = False
                    rod.fully_raised = True
                    rod.inserted = False

        # Завершение опускания
        for rod in rods:
            if rod.lowering:
                if now - rod.lowering_start_time >= 5:
                    rod.lowering = False
                    rod.fully_raised = False
                    rod.inserted = True

        # Температура стремится к мощности
        modifier = 1.0
        if cooling_mode == 'low':
            modifier = 1.2
        elif cooling_mode == 'high':
            modifier = 0.7

        target_temp = int(sfkre / 25) * 5 * modifier
        if temperature < target_temp:
            temperature += min(10, target_temp - temperature)
        elif temperature > target_temp:
            temperature -= min(10, temperature - target_temp)
        if temperature < 20:
            temperature = 20

        if auto_protection_enabled and temperature >= 900:
            az5_action()

        if temperature >= 1300 and not exploded:
            exploded = True
            # Воспроизвести звук взрыва
            if not explosive_alarm_played:
                explosive_alarm_sound.play()
                explosive_alarm_played = True
            # Остановить звук АЗ-5 после взрыва
            if az5_alarm_channel is not None:
                az5_alarm_channel.stop()
                az5_alarm_channel = None
            # Остановить все остальные звуки, кроме взрыва
            # (не вызываем pygame.mixer.stop(), чтобы не прервать звук взрыва)

        # Остановить звук АЗ-5, если СФКРЭ упал до 0 или произошёл взрыв
        if az5_alarm_channel is not None and (sfkre <= 0 or exploded):
            az5_alarm_channel.stop()
            az5_alarm_channel = None

def draw_lamp_counter(x, y, value):
    # Бумажка над счётчиком
    label_text = 'Мощность СФКРЭ'
    txt = font.render(label_text, True, (60, 40, 10))
    txt_rect = txt.get_rect(center=(x + 110, y - 18))
    paper_pad_x = 8
    paper_pad_y = 4
    paper_rect = pygame.Rect(
        txt_rect.left - paper_pad_x,
        txt_rect.top - paper_pad_y,
        txt_rect.width + 2 * paper_pad_x,
        txt_rect.height + 2 * paper_pad_y
    )
    pygame.draw.rect(screen, (245, 242, 225), paper_rect, border_radius=8)
    pygame.draw.rect(screen, (200, 200, 200), paper_rect, 2, border_radius=8)
    screen.blit(txt, txt_rect)
    # Ламповый фон
    lamp_rect = pygame.Rect(x, y, 220, 90)
    pygame.draw.rect(screen, LAMP_BG, lamp_rect, border_radius=18)
    pygame.draw.rect(screen, (80, 60, 30), lamp_rect, 4, border_radius=18)
    # Цифры по центру
    str_val = str(int(value)).rjust(5, "0")
    total_width = len(str_val) * 36
    start_x = x + (220 - total_width) // 2
    # Центрируем по вертикали, чуть ниже центра (но меньше чем раньше)
    digit_height = font_lamp.get_height()
    start_y = y + (90 - digit_height) // 2 + 4
    for i, ch in enumerate(str_val):
        digit_surf = font_lamp.render(ch, True, LAMP_DIGIT)
        screen.blit(digit_surf, (start_x + i*36, start_y))
    # (Надпись СФКРЭ убрана)

def draw_rods():
    for rod in rods:
        if rod.fully_raised:
            color = RED
        elif rod.raising:
            color = ORANGE
        elif rod.lowering:
            color = BLUE
        elif not rod.inserted:
            color = BLUE
        else:
            color = GREEN
        if (rod.i, rod.j) in rod_selected:
            color = YELLOW
        pygame.draw.rect(screen, color, rod.rect(), border_radius=8)
        pygame.draw.rect(screen, BLACK, rod.rect(), 2, border_radius=8)

def draw_info():
    t_text = font.render(f"Температура: {temperature}°C", True, BLACK)
    ap_text = font.render(f"АПЗ: {'вкл' if auto_protection_enabled else 'выкл'}", True, BLACK)
    screen.blit(t_text, (700, 50))
    screen.blit(ap_text, (700, 80))
    if exploded:
        boom = font.render("💥 ВЗРЫВ РЕАКТОРА 💥", True, RED)
        screen.blit(boom, (700, 150))

# --- Коллбэки кнопок ---

def select_rod_callback(i, j):
    if exploded:
        return
    if len(rod_selected) < 4 and (i, j) not in rod_selected:
        rod_selected.append((i, j))

def reset_selection():
    if exploded:
        return
    rod_selected.clear()

def raise_rods():
    if exploded:
        return
    now = time.time()
    for rod in rods:
        if (rod.i, rod.j) in rod_selected and rod.inserted and not rod.fully_raised and not rod.raising and not rod.lowering:
            rod.raising = True
            rod.raising_start_time = now

def lower_rods():
    if exploded:
        return
    now = time.time()
    for rod in rods:
        if (rod.i, rod.j) in rod_selected and (not rod.inserted or rod.fully_raised) and not rod.lowering and not rod.raising:
            rod.lowering = True
            rod.lowering_start_time = now

def toggle_cooling_low():
    global cooling_mode, temperature, sfkre, exploded
    if exploded:
        return
    cooling_mode = 'low'
    # Меньше воды — температура растёт только если есть мощность, СФКРЭ растёт только если оно больше 0
    if sfkre > 0:
        temperature = min(temperature + 100, 2000)
        sfkre = min(sfkre + 10, 99999)

def toggle_cooling_high():
    global cooling_mode, temperature, sfkre, exploded
    if exploded:
        return
    cooling_mode = 'high'
    # Больше воды — температура и СФКРЭ падают
    temperature = max(temperature - 100, 0)
    sfkre = max(sfkre - 10, 0)

def toggle_auto_protect():
    global auto_protection_enabled, exploded
    if exploded:
        return
    auto_protection_enabled = not auto_protection_enabled

# --- MUF SWITCH логика ---
def muf_switch_action():
    global sfkre, temperature, muf_switch_active, muf_switch_decay_target, muf_switch_last_time, exploded
    if exploded:
        return
    now = time.time()
    if now - muf_switch_last_time < 2:  # Быстрее, чем АЗ-5
        return
    muf_switch_last_time = now
    for rod in rods:
        rod.inserted = True
        rod.raising = False
        rod.raising_start_time = None
        rod.fully_raised = False
        rod.lowering = False
        rod.lowering_start_time = None
    if sfkre > 0:
        sfkre += 50  # Можно сделать меньше, чем у АЗ-5
    temperature += 20
    muf_switch_active = True
    muf_switch_decay_target = 0

# --- Переключатель Ключ питания муфт ---
class ToggleSwitch:
    def __init__(self, x, y, w, h, label, callback):
        self.x = x
        self.y = y
        self.w = w
        self.h = h
        self.label = label
        self.callback = callback
        self.state = False
        self.last_state = False
        self.anim_angle = 270  # угол для анимации (270 - вертикально, 180 - горизонтально)
        self.target_angle = 270
        self.animating = False
        self.anim_speed = 8  # скорость анимации (градусов за кадр)

    def draw(self):
        # Крепление (чёрный квадрат, чуть меньше всей области, по центру)
        base_size = int(self.h * 1.1)
        base_rect = pygame.Rect(self.x + self.w // 2 - base_size // 2, self.y + self.h // 2 - base_size // 2, base_size, base_size)
        pygame.draw.rect(screen, (20, 20, 20), base_rect, border_radius=10)
        # Бумажный фон под надписью
        label_text = 'Питан. муфт'
        txt = font.render(label_text, True, (60, 40, 10))
        # Бумажка и текст чуть выше центра переключателя
        txt_rect = txt.get_rect(center=(self.x + self.w // 2, self.y - 24))
        paper_pad_x = 8
        paper_pad_y = 4
        paper_rect = pygame.Rect(
            txt_rect.left - paper_pad_x,
            txt_rect.top - paper_pad_y,
            txt_rect.width + 2 * paper_pad_x,
            txt_rect.height + 2 * paper_pad_y
        )
        pygame.draw.rect(screen, (245, 242, 225), paper_rect, border_radius=8)
        pygame.draw.rect(screen, (200, 200, 200), paper_rect, 2, border_radius=8)
        screen.blit(txt, txt_rect)
        # Круглый переключатель
        knob_center = (self.x + self.w // 2, self.y + self.h // 2)
        knob_radius = self.h // 2 - 4
        pygame.draw.circle(screen, (80, 80, 80), knob_center, knob_radius+4)
        pygame.draw.circle(screen, (30, 30, 30), knob_center, knob_radius)
        pygame.draw.circle(screen, (0, 0, 0), knob_center, knob_radius, 2)
        angle = self.anim_angle
        line_len = knob_radius * 0.85
        x1 = int(knob_center[0] + line_len * math.cos(math.radians(angle)))
        y1 = int(knob_center[1] + line_len * math.sin(math.radians(angle)))
        x2 = int(knob_center[0] - line_len * math.cos(math.radians(angle)))
        y2 = int(knob_center[1] - line_len * math.sin(math.radians(angle)))
        pygame.draw.line(screen, (0, 0, 0), (x1, y1), (x2, y2), 6)
        pygame.draw.circle(screen, (100, 100, 100), knob_center, 6)

    def update(self):
        # Анимация поворота
        if self.animating:
            if abs(self.anim_angle - self.target_angle) < self.anim_speed:
                self.anim_angle = self.target_angle
                self.animating = False
            elif self.anim_angle < self.target_angle:
                self.anim_angle += self.anim_speed
            else:
                self.anim_angle -= self.anim_speed

    def handle_event(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN:
            mouse_pos = event.pos
            knob_center = (self.x + self.w // 2, self.y + self.h // 2)
            knob_radius = self.h // 2
            # Проверка попадания по кругу
            if (mouse_pos[0] - knob_center[0]) ** 2 + (mouse_pos[1] - knob_center[1]) ** 2 <= knob_radius ** 2:
                self.state = not self.state
                # Анимация: вертикально (270) -> горизонтально (180) и обратно
                self.target_angle = 180 if self.state else 270
                self.animating = True
                if self.state and not self.last_state:
                    self.callback()
        if event.type == pygame.MOUSEBUTTONUP:
            self.last_state = self.state

# --- Создание переключателя ---
muf_switch = ToggleSwitch(420, 100, 120, 48, 'Питан. муфт', muf_switch_action)

# --- Круглая кнопка АЗ-5 ---
class RoundButton:
    def __init__(self, x, y, r, text, color, callback):
        self.x = x
        self.y = y
        self.r = r
        self.text = text
        self.color = color
        self.callback = callback
        self.hovered = False

    def draw(self):
        # Круглая кнопка
        pygame.draw.circle(screen, self.color, (self.x, self.y), self.r)
        pygame.draw.circle(screen, (0,0,0), (self.x, self.y), self.r, 3)
        # (Надпись убрана, она теперь только на бумажке)

    def handle_event(self, event):
        if event.type == pygame.MOUSEMOTION:
            dx = event.pos[0] - self.x
            dy = event.pos[1] - self.y
            self.hovered = dx*dx + dy*dy <= self.r*self.r
        if event.type == pygame.MOUSEBUTTONDOWN:
            dx = event.pos[0] - self.x
            dy = event.pos[1] - self.y
            if dx*dx + dy*dy <= self.r*self.r:
                self.callback()

# --- Бумажка для АЗ-5 ---
def draw_az5_paper():
    label_text = 'АЗ-5'
    txt = font.render(label_text, True, (60, 40, 10))
    txt_rect = txt.get_rect(center=(az5_btn.x, az5_btn.y - az5_btn.r - 18))
    paper_pad_x = 8
    paper_pad_y = 4
    paper_rect = pygame.Rect(
        txt_rect.left - paper_pad_x,
        txt_rect.top - paper_pad_y,
        txt_rect.width + 2 * paper_pad_x,
        txt_rect.height + 2 * paper_pad_y
    )
    pygame.draw.rect(screen, (245, 242, 225), paper_rect, border_radius=8)
    pygame.draw.rect(screen, (200, 200, 200), paper_rect, 2, border_radius=8)
    screen.blit(txt, txt_rect)

# --- Создание круглой кнопки АЗ-5 ---
az5_btn = RoundButton(290, 120, 32, "АЗ-5", (255,80,80), az5_action)

# --- Кнопки ---
buttons.clear()
# Круглая кнопка АЗ-5 и переключатель над стержнями, смещены левее
# (draw_az5_paper и az5_btn.draw() вызываются отдельно)
# Остальные кнопки справа
buttons.append(Button(700, 170, 120, 40, "Сброс", BUTTON_FACE, reset_selection))
buttons.append(Button(700, 220, 120, 40, "Поднять", (180,220,180), raise_rods))
buttons.append(Button(700, 270, 120, 40, "Опустить", (220,180,180), lower_rods))
buttons.append(Button(700, 320, 120, 40, "САОР", (120,180,255), saor_action))
buttons.append(Button(700, 370, 120, 40, "ГЦН -", (255,255,255), toggle_cooling_low))
buttons.append(Button(700, 420, 120, 40, "ГЦН +", (255,120,120), toggle_cooling_high))
buttons.append(Button(700, 470, 120, 40, "Авт. Защ.", (255,255,120), toggle_auto_protect))

# --- Основной цикл ---
clock = pygame.time.Clock()

while True:
    screen.fill((60, 80, 100))
    draw_rods()
    draw_lamp_counter(60, 580, sfkre)
    draw_info()
    for b in buttons:
        b.draw()
    draw_az5_paper()
    az5_btn.draw()
    muf_switch.update()
    muf_switch.draw()

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            pygame.quit()
            sys.exit()
        elif event.type == pygame.MOUSEMOTION:
            for b in buttons:
                b.handle_event(event)
            az5_btn.handle_event(event)
            muf_switch.handle_event(event)
        elif event.type == pygame.MOUSEBUTTONDOWN:
            pos = event.pos
            for rod in rods:
                if rod.rect().collidepoint(pos):
                    select_rod_callback(rod.i, rod.j)
            for b in buttons:
                b.handle_event(event)
            az5_btn.handle_event(event)
            muf_switch.handle_event(event)
        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_m:
                muf_switch_action()
        elif event.type == pygame.MOUSEBUTTONUP:
            muf_switch.handle_event(event)

    if not exploded:
        update_reactor()

    pygame.display.flip()
    clock.tick(60)

