clear; clc;
% =========================
% LSL SETUP
% =========================
lib = lsl_loadlib();
info = lsl_streaminfo(lib,'Markers','Markers',1,0,'cf_string','ssvep_markers');
outlet = lsl_outlet(info);
% =========================
% PARAMETERS
% =========================
MONITOR_HZ = 60;
freqs = [6.5, 8.37, 10.84, 12, 14.87];
keys    = {'1','2','3','4','5'};
fingers = {'thumb','index','middle','ring','pinky'};
 
COLOR_ON  = [0 0 0];       % black
COLOR_OFF = [255 255 255]; % white
% =========================
% TRACKING
% =========================
trialCount = 0;
fingerCounts = zeros(1,5);
% =========================
% WINDOW
% =========================
Screen('Preference', 'SkipSyncTests', 1);
[win, rect] = Screen('OpenWindow', 0, COLOR_OFF);
KbName('UnifyKeyNames');
% =========================
% MAIN LOOP
% =========================
while true
    % ---- REST ----
    wait_for_key({'e'}, 'Close your eyes and press E', outlet, 'REST_START', win);
    % ---- RELAX ----
    wait_for_key({'o'}, 'Open your eyes and press O', outlet, 'RELAX_START', win);
    % ---- FIXATION ----
    Screen('FillRect', win, COLOR_OFF);
    DrawFormattedText(win, '+', 'center', 'center', [0 0 0]);
    Screen('Flip', win);
    WaitSecs(5);
    % ---- USER SELECTION ----
    key = wait_for_key(keys, ...
        'Press 1-5 (1=Thumb ... 5=Pinky)', ...
        outlet, '', win);
    idx = find(strcmp(keys, key));
    if isempty(idx)
        continue;
    end
    target = fingers{idx};
    % ---- SHOW TARGET ----
    Screen('FillRect', win, COLOR_OFF);
    DrawFormattedText(win, ['Focus on: ' upper(target)], ...
        'center', 'center', [0 0 0]);
    Screen('Flip', win);
    WaitSecs(1);
    % ---- UPDATE COUNTS ----
    trialCount = trialCount + 1;
    fingerCounts(idx) = fingerCounts(idx) + 1;
    % ---- FLICKER ----
    flicker_fullscreen(freqs(idx), target, win, ...
        COLOR_ON, COLOR_OFF, MONITOR_HZ, outlet, ...
        trialCount, fingerCounts);
end
% =========================
% FLICKER FUNCTION
% =========================
function flicker_fullscreen(freq, target, win, ...
    COLOR_ON, COLOR_OFF, MONITOR_HZ, outlet, ...
    trialCount, fingerCounts)
    frame = 0;
    tStart = GetSecs;
    marker = ['TRIAL_' num2str(trialCount) '_' target];
    outlet.push_sample({marker});
    disp(['Sent marker: ' marker]);
    while GetSecs - tStart < 6
        % Flicker logic
        period = round(MONITOR_HZ / freq);
        is_on = mod(frame, period) < (period/2);
        % Draw background
        if is_on
            Screen('FillRect', win, COLOR_ON);
        else
            Screen('FillRect', win, COLOR_OFF);
        end
        % Draw stats
        draw_stats(win, trialCount, fingerCounts, is_on);
        Screen('Flip', win);
        frame = frame + 1;
        % Exit check
        [keyIsDown,~,keyCode] = KbCheck;
        if keyIsDown && keyCode(KbName('ESCAPE'))
            sca;
            return;
        end
    end
    outlet.push_sample({'TRIAL_END'});
    disp('Sent marker: TRIAL_END');
end
% =========================
% WAIT FOR KEY
% =========================
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
                    disp(['Sent marker: ' marker]);
                end
                pressedKey = key;
                % wait for release (important!)
                KbReleaseWait;
                break;
            elseif strcmpi(key,'ESCAPE')
                sca;
                return;
            end
        end
    end
end
% =========================
% DRAW STATS
% =========================
function draw_stats(win, trialCount, fingerCounts, is_on)
    if is_on
        textColor = [255 255 255];
    else
        textColor = [0 0 0];
    end
    msg = sprintf(['Trial: %d\n' ...
        'Thumb : %d\n' ...
        'Index : %d\n' ...
        'Middle: %d\n' ...
        'Ring  : %d\n' ...
        'Pinky : %d'], ...
        trialCount, ...
        fingerCounts(1), ...
        fingerCounts(2), ...
        fingerCounts(3), ...
        fingerCounts(4), ...
        fingerCounts(5));
    DrawFormattedText(win, msg, 20, 20, textColor);
end