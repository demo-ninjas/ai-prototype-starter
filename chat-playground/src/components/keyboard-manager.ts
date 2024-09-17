
class KeyboardManager {
    keyMap: Map<string, string>;

    constructor() {
        // Listen for keydown and keyup events
        document.addEventListener('keydown', this.handleKeyDown.bind(this));
        document.addEventListener('keyup', this.handleKeyUp.bind(this));

        // Map key codes to event names
        this.keyMap = new Map();
        this.keyMap.set('ArrowUp', 'up');
        this.keyMap.set('ArrowDown', 'down');
        this.keyMap.set('ArrowLeft', 'left');
        this.keyMap.set('ArrowRight', 'right');
        this.keyMap.set('Enter', 'enter');
        this.keyMap.set('Escape', 'esc');
        this.keyMap.set(' ', 'space');
        this.keyMap.set(']', 'toggle-right-panel');
        this.keyMap.set('[', 'toggle-left-panel');
        this.keyMap.set('/', 'focus-chat');
    }
    
    handleKeyDown(event: KeyboardEvent) {
        const key = this.keyMap.get(event.key);
        if (key) {
            document.dispatchEvent(new CustomEvent(key + '-keydown', { detail: event }));
        }
    }
    handleKeyUp(event: KeyboardEvent) {
        const key = this.keyMap.get(event.key);
        if (key) {
            if (key == "toggle-right-panel") {
                let rightPanel = document.getElementById('app-aside-right');
                if (rightPanel) {
                    rightPanel.classList.toggle('hide-right');
                }
            } else if (key == "toggle-left-panel") {
                let leftPanel = document.getElementById('app-aside-left');
                if (leftPanel) {
                    leftPanel.classList.toggle('hide-left');
                }
            } else if (key == "focus-chat") {
                let input = document.querySelector('textarea[aria-label="Message input box"]');
                if (input) {
                  // @ts-ignore
                  input.focus();
                }
            }

            document.dispatchEvent(new CustomEvent(key + '-keyup', { detail: event }));
        }
    }
}

export default KeyboardManager;