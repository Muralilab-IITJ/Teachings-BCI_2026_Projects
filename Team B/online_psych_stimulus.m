clear; clc;
% ── LSL Setup ───────────────────────────────
lib    = lsl_loadlib();
info   = lsl_streaminfo(lib, 'Markers', 'Markers', 1, 0, 'cf_string', 'ssvep_markers');
outlet = lsl_outlet(info);
% ── Parameters ──────────────────────────────
MONITOR_HZ = 60;
FIX_SEC     = 3.0;
TRIAL_SEC   = 4.0;
COLOR_ON  = [0 0 0];       % black
COLOR_OFF = [255 255 255]; % white
keys    = {'1','2','3','4','5'};
fingers = {'thumb','index','middle','ring','pinky'};
labels  = {'Thumb','Index','Middle','Ring','Pinky'};
freqs   = [6.5, 8.37, 10.84, 12, 14.87];
% ── Screen ──────────────────────────────────
Screen('Preference','SkipSyncTests',1);
[win, ~] = Screen('OpenWindow', 0, COLOR_OFF);
KbName('UnifyKeyNames');
trial_num = 0;
% ── MAIN LOOP ───────────────────────────────
while true
    % ── USER INPUT (KEYBOARD) ───────────────
    key = wait_for_key(keys, ...
        'Press 1-5 (1=Thumb ... 5=Pinky)', ...
        outlet, '', win);
    finger_idx = str2double(key);
    % ── FIXATION CROSS ──────────────────────
    Screen('FillRect', win, COLOR_OFF);
    DrawFormattedText(win, '+', 'center', 'center', [0 0 0]);
    Screen('Flip', win);
    WaitSecs(FIX_SEC);
    % ── SEND TRIAL MARKER ───────────────────
    trial_num = trial_num + 1;
    marker = ['TRIAL_' num2str(trial_num) '_' fingers{finger_idx}];
    outlet.push_sample({marker});
    fprintf('Sent: %s\n', marker);
    % ── FLICKER ─────────────────────────────
    period = round(MONITOR_HZ / freqs(finger_idx));
    frame  = 0;
    tStart = GetSecs;
    while GetSecs - tStart < TRIAL_SEC
        is_on = mod(frame, period) < (period/2);
        if is_on
            Screen('FillRect', win, COLOR_ON);
            DrawFormattedText(win, labels{finger_idx}, ...
                'center', 40, [255 255 255]);
        else
            Screen('FillRect', win, COLOR_OFF);
            DrawFormattedText(win, labels{finger_idx}, ...
                'center', 40, [0 0 0]);
        end
        Screen('Flip', win);
        frame = frame + 1;
        % ESC to quit
        [keyDown, ~, keyCode] = KbCheck;
        if keyDown && keyCode(KbName('ESCAPE'))
            outlet.push_sample({'TRIAL_END'});
            sca;
            return;
        end
    end
    % ── END MARKER ──────────────────────────
    outlet.push_sample({'TRIAL_END'});
    fprintf('Sent: TRIAL_END\n\n');
end
% ── WAIT FOR KEY FUNCTION ───────────────────
function pressedKey = wait_for_key(validKeys, message, outlet, marker, win)
    while true
        Screen('FillRect', win, [255 255 255]);
        DrawFormattedText(win, message, 'center', 'center', [0 0 0]);
        Screen('Flip', win);
        [keyIsDown,~,keyCode] = KbCheck;
        if keyIsDown
            key = KbName(find(keyCode));
            if iscell(key), key = key{1}; end
            if any(strcmpi(key, validKeys))
                if ~isempty(marker)
                    outlet.push_sample({marker});
                end
                pressedKey = key;
                KbReleaseWait; % prevent key repeat
                break;
            elseif strcmpi(key,'ESCAPE')
                sca;
                return;
            end
        end
    end
end