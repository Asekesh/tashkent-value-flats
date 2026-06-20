from aiogram.fsm.state import State, StatesGroup


class NewAlert(StatesGroup):
    deal_type = State()
    districts = State()
    rooms = State()
    price = State()
    area = State()
    floor = State()
    discount = State()
    commission = State()
    name = State()


class Feedback(StatesGroup):
    kind = State()
    text = State()
