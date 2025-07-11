import sys
import os
import time
import asyncio
from prompt_toolkit.shortcuts import message_dialog, radiolist_dialog, input_dialog
from prompt_toolkit import prompt
from operate.exceptions import ModelNotRecognizedException
import platform

# from operate.models.prompts import USER_QUESTION, get_system_prompt
from operate.models.prompts import (
    USER_QUESTION,
    get_system_prompt,
)
from operate.config import Config
from operate.utils.style import (
    ANSI_GREEN,
    ANSI_RESET,
    ANSI_YELLOW,
    ANSI_RED,
    ANSI_BRIGHT_MAGENTA,
    ANSI_BLUE,
    style,
    strip_ansi_codes,
)
from operate.utils.operating_system import OperatingSystem
from operate.models.apis import get_next_action

# Load configuration
config = Config()
operating_system = OperatingSystem()


from operate.models.model_configs import MODELS

def display_welcome_message():
    welcome_message = """
Welcome to Self-Operating Computer!

This tool allows multimodal models to operate a computer.
It uses screen vision and decides on mouse/keyboard actions.

Let's get started!
"""
    print(welcome_message)


def select_openrouter_model_interactively():
    text_content = f"""{ANSI_GREEN}Please enter the full OpenRouter model name.{ANSI_RESET}
{ANSI_YELLOW}Ensure the model supports both image and text input modalities.{ANSI_RESET}
{ANSI_YELLOW}You can find a list of suitable models here: https://openrouter.ai/models?fmt=cards&input_modalities=image%2Ctext{ANSI_RESET}
{ANSI_YELLOW}Examples: google/gemini-2.0-flash-001, openai/gpt-4o, anthropic/claude-3-opus{ANSI_RESET}"""
    model_name = input_dialog(
        title="OpenRouter Model Selection",
        text=strip_ansi_codes(text_content),
    ).run()
    if model_name is None:
        sys.exit("OpenRouter model selection cancelled. Exiting.")
    return model_name

def select_model_interactively():
    print("Attempting to display model selection dialog...")
    models = [(name, config["display_name"]) for name, config in MODELS.items()]
    
    selected_model = radiolist_dialog(
        title="Model Selection",
        text="Please select a model to use:",
        values=models,
    ).run()
    
    if selected_model == "openrouter":
        selected_model = select_openrouter_model_interactively()
    
    if selected_model is None:
        print("Dialog was cancelled or failed to display.")
        
    return selected_model


def get_custom_system_prompt():
    if os.getenv("CUSTOM_SYSTEM_PROMPT"): # If env variable exists, don't show the screen
        return os.getenv("CUSTOM_SYSTEM_PROMPT")

    system_prompt_options = [
        ("none", "No custom system prompt (use default model prompt)"),
        ("file", "Load from a text file"),
        ("env", "Load from environment variable (CUSTOM_SYSTEM_PROMPT)"),
    ]

    selected_option = radiolist_dialog(
        title="Custom System Prompt",
        text="""
How would you like to provide a custom system prompt?

- 'No custom system prompt': Use the default prompt for the selected model.
- 'Load from a text file': Specify a path to a .txt file containing your prompt.
- 'Load from environment variable': Use the value of the CUSTOM_SYSTEM_PROMPT environment variable.
""",
        values=system_prompt_options,
    ).run()

    if selected_option == "file":
        file_path = prompt("Enter the path to the system prompt file:")
        try:
            with open(file_path, "r") as f:
                return f.read()
        except FileNotFoundError:
            print(f"{ANSI_RED}Error: File not found at {file_path}{ANSI_RESET}")
            return None
    elif selected_option == "env":
        return os.getenv("CUSTOM_SYSTEM_PROMPT")
    return None


def main(model, terminal_prompt, voice_mode=False, verbose_mode=False):
    """
    Main function for the Self-Operating Computer.

    Parameters:
    - model: The model used for generating responses.
    - terminal_prompt: A string representing the prompt provided in the terminal.
    - voice_mode: A boolean indicating whether to enable voice mode.

    Returns:
    None
    """

    mic = None
    # Initialize `WhisperMic`, if `voice_mode` is True

    config.verbose = verbose_mode

    display_welcome_message()

    if not model:
        openrouter_model_env = os.getenv("OPENROUTER_MODEL")
        if openrouter_model_env:
            model = f"openrouter_internal_{openrouter_model_env}"
        else:
            model = select_model_interactively()
            if not model:  # User cancelled model selection
                sys.exit("Model selection cancelled. Exiting.")
            # If the selected model is from OpenRouter, add the internal prefix
            if model and MODELS.get(model, {}).get("provider") == "openrouter":
                model = f"openrouter_internal_{model}"

    config.validation(model, voice_mode)

    custom_system_prompt = get_custom_system_prompt()

    if voice_mode:
        try:
            from whisper_mic import WhisperMic

            # Initialize WhisperMic if import is successful
            mic = WhisperMic()
        except ImportError:
            print(
                "Voice mode requires the 'whisper_mic' module. Please install it using 'pip install -r requirements-audio.txt'"
            )
            sys.exit(1)

    # # Clear the console
    if platform.system() == "Windows":
        os.system("cls")
    else:
        print("\033c", end="")

    if terminal_prompt:  # Skip objective prompt if it was given as an argument
        objective = terminal_prompt
    elif voice_mode:
        print(
            f"{ANSI_GREEN}[Self-Operating Computer]{ANSI_RESET} Listening for your command... (speak now)"
        )
        try:
            objective = mic.listen()
        except Exception as e:
            print(f"{ANSI_RED}Error in capturing voice input: {e}{ANSI_RESET}")
            return  # Exit if voice input fails
    else:
        print(
            f"[{ANSI_GREEN}Self-Operating Computer {ANSI_RESET}|{ANSI_BRIGHT_MAGENTA} {model}{ANSI_RESET}]\n{USER_QUESTION}"
        )
        print(f"{ANSI_YELLOW}[User]{ANSI_RESET}")
        objective = prompt(style=style)

    system_prompt = get_system_prompt(model, objective, custom_system_prompt)
    system_message = {"role": "system", "content": system_prompt}
    messages = [system_message]

    loop_count = 0

    session_id = None

    while True:
        if config.verbose:
            print("[Self Operating Computer] loop_count", loop_count)
        try:
            operations, session_id = asyncio.run(
                get_next_action(model, messages, objective, session_id)
            )

            stop = operate(operations, model)
            if stop == "done":
                # Task completed, prompt for next objective
                print(f"[{ANSI_GREEN}Self-Operating Computer {ANSI_RESET}|{ANSI_BRIGHT_MAGENTA} {model}{ANSI_RESET}]\n{USER_QUESTION}")
                print(f"{ANSI_YELLOW}[User]{ANSI_RESET}")
                objective = prompt(style=style)
                system_prompt = get_system_prompt(model, objective, custom_system_prompt)
                system_message = {"role": "system", "content": system_prompt}
                messages = [system_message] # Reset messages for new objective
                loop_count = 0 # Reset loop count for new objective
                session_id = None # Reset session ID for new objective
                continue # Continue to the next iteration of the main loop
            elif stop:
                break

            loop_count += 1
            if loop_count > 10:
                break
        except ModelNotRecognizedException as e:
            print(
                f"{ANSI_GREEN}[Self-Operating Computer]{ANSI_RED}[Error] -> {e} {ANSI_RESET}"
            )
            break
        except Exception as e:
            print(
                f"{ANSI_GREEN}[Self-Operating Computer]{ANSI_RED}[Error] -> {e} {ANSI_RESET}"
            )
            break


def operate(operations, model):
    if config.verbose:
        print("[Self Operating Computer][operate]")
    for operation in operations:
        if config.verbose:
            print("[Self Operating Computer][operate] operation", operation)
        # wait one second
        time.sleep(1)
        operate_type = operation.get("operation").lower()
        operate_thought = operation.get("thought")
        operate_detail = ""
        if config.verbose:
            print("[Self Operating Computer][operate] operate_type", operate_type)

        if operate_type == "press" or operate_type == "hotkey":
            keys = operation.get("keys")
            operate_detail = keys
            operating_system.press(keys)
        elif operate_type == "write":
            content = operation.get("content")
            operate_detail = content
            operating_system.write(content)
        elif operate_type == "click":
            x = operation.get("x")
            y = operation.get("y")
            click_detail = {"x": x, "y": y}
            operate_detail = click_detail

            operating_system.mouse(click_detail)
        elif operate_type == "done":
            summary = operation.get("summary")
            print(
                f"[{ANSI_GREEN}Self-Operating Computer {ANSI_RESET}|{ANSI_BRIGHT_MAGENTA} {model}{ANSI_RESET}]"
            )
            print(f"{ANSI_BLUE}Objective Complete: {ANSI_RESET}{summary}" + "\n")
            return "done"
        else:
            print(
                f"{ANSI_GREEN}[Self-Operating Computer]{ANSI_RED}[Error] unknown operation response :({ANSI_RESET}"
            )
            print(
                f"{ANSI_GREEN}[Self-Operating Computer]{ANSI_RED}[Error] AI response {ANSI_RESET}{operation}"
            )
            return True

        print(
            f"[{ANSI_GREEN}Self-Operating Computer {ANSI_RESET}|{ANSI_BRIGHT_MAGENTA} {model}{ANSI_RESET}]"
        )
        print(f"{operate_thought}")
        print(f"{ANSI_BLUE}Action: {ANSI_RESET}{operate_type} {operate_detail}\n")

    return False
