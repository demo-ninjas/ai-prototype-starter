

export const DELTA_STATUS_NEW = 'new';
export const DELTA_STATUS_CAPTURING = 'capturing';
export const DELTA_STATUS_EXPIRED = 'expired';


export class MessageDelta {
    delta: string = '';
    full: string = '';
    lang: string = 'en';
    content: any = '';
    speech: string = '';
    id: string = '';
    status: string = DELTA_STATUS_NEW;

    expiredMessages:any = {};

    constructor() {
        this.reset();
    }

    reset() {
        this.delta = '';
        this.full = '';
        this.lang = 'en';
        this.content = '';
        this.speech = '';
        this.id = '';
        this.status = DELTA_STATUS_NEW;
    }

    isEmpty() {
        return this.delta === '';
    }

    addDelta(delta: string) {
        this.delta += delta;
        this.full += delta;
    }

    resetDelta() {
        this.delta = '';
    }

    setExpired() {
        this.status = DELTA_STATUS_EXPIRED;
        this.expiredMessages[this.id] = true;
    }

    isExpired() {
        return this.status === DELTA_STATUS_EXPIRED || this.expiredMessages[this.id] === true;
    }

    static isMessageExpired(id:string, delta:MessageDelta) {
        return delta.expiredMessages[id] === true;
    }

    clearExpired(id:string) {
        delete this.expiredMessages[id];
    }
}

