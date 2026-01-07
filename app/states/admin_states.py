from aiogram.fsm.state import State, StatesGroup


class AdminStates(StatesGroup):
    waiting_for_source_channel = State()
    waiting_for_target_channel = State()
    # waiting_for_channel_to_remove = State() # Not used if using inline buttons for removal
