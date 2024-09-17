import { StyleOptions } from  'botframework-webchat';

const styleOptions:StyleOptions = {  
    // Send box
    hideSendBox: false,           
    microphoneButtonColorOnDictate: '#F33',
    
    sendBoxBackground: '#284235',
    sendBoxTextColor: '#fff',
    sendBoxPlaceholderColor: '#beb',
    sendBoxButtonColor: '#fff',
    sendBoxTextWrap: true,
    sendBoxButtonKeyboardFocusIndicatorBorderColor: '#fff',
    sendBoxButtonShadeColorOnActive: '#fff',
    sendBoxButtonColorOnActive: '#ccc',
    sendBoxHeight: '2rem',

    // Visually show spoken text
    showSpokenText: false,

    // Add styleOptions to customize Web Chat canvas
    hideUploadButton: true,
    emojiSet: true,
    backgroundColor: '#eee',
    botAvatarInitials: 'YT',
    accent: '#00809d',

    //Suggested Actions
    suggestedActionLayout: 'carousel', //other option is horizontally: 'stacked'
    suggestedActionBackground: 'White',
    suggestedActionBorderColor: undefined,
    suggestedActionBorderRadius: 10,
    suggestedActionBorderStyle: 'none',
    suggestedActionBorderWidth: 2,
    suggestedActionDisabledBackground: '#fff',
    suggestedActionDisabledBorderColor: '#fff',
    suggestedActionDisabledBorderStyle: 'solid',
    suggestedActionDisabledBorderWidth: 2,
    suggestedActionDisabledTextColor: undefined,
    suggestedActionHeight: 40,
    suggestedActionImageHeight: 20,
    suggestedActionTextColor: undefined,

    //Bot Avatar
    botAvatarBackgroundColor: "#eee",
    botAvatarImage: './robot.svg',
    userAvatarImage: './user.svg',

    //Bubbles
    bubbleBackground: '#190e7a',
    bubbleBorderColor: 'White',
    bubbleTextColor: 'White',
    bubbleBorderRadius: 10,
    bubbleMaxWidth: 800, 
    bubbleNubOffset: -30,
    bubbleNubSize: 10,
    bubbleFromUserBackground: '#286235',
    bubbleFromUserBorderColor: '#014e05',
    bubbleFromUserTextColor: 'White',
    bubbleFromUserBorderRadius: 10
};

export default styleOptions;