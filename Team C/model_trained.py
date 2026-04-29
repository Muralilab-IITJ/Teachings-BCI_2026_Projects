# -*- coding: utf-8 -*-
"""
Created on Fri Apr 17 11:59:43 2026

@author: prash

FINAL Mind Wandering Detection System - FIXED VERSION
Addresses overfitting and threshold misalignment
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import os
from scipy.signal import welch, find_peaks, butter, filtfilt, iirnotch, detrend
from scipy.stats import zscore
from sklearn.svm import SVC
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import StratifiedKFold, cross_val_score, train_test_split
from sklearn.metrics import (classification_report, confusion_matrix, 
                           accuracy_score, roc_auc_score)
from sklearn.inspection import permutation_importance
from sklearn.feature_selection import SelectKBest, f_classif
import pickle
import warnings
warnings.filterwarnings('ignore')

plt.style.use('seaborn-v0_8-whitegrid')
plt.rcParams['font.size'] = 10
plt.rcParams['figure.dpi'] = 100

# ==============================================================================
# CONFIGURATION - UPDATED THRESHOLDS
# ==============================================================================
class Config:
    DATA_DIR = r'C:/Users/prash/Downloads/Sem_2/BCI/data'
    TARGET_SR = 128
    WINDOW_SEC = 10
    
    # ADAPTIVE: Will be set based on data distribution
    MW_THRESHOLD_HIGH = None  # Set to 75th percentile of MW class
    MW_THRESHOLD_LOW = None   # Set to 25th percentile of Focused class
    
    PLOT_FILE = 'fixed_svm_model.png'
    
    # Filter settings
    NOTCH_FREQ = 50          
    EEG_BANDPASS = (1, 40)   
    ECG_BANDPASS = (0.5, 40) 
    EOG_BANDPASS = (0.1, 10) 

# ==============================================================================
# FEATURE EXTRACTOR - with Log-transform option
# ==============================================================================
class MWFeatureExtractor:
    def __init__(self, sr=128):
        self.sr = sr
        self._init_filters()
    
    def _init_filters(self):
        nyq = self.sr / 2
        # EEG
        low, high = Config.EEG_BANDPASS[0] / nyq, Config.EEG_BANDPASS[1] / nyq
        self.b_eeg, self.a_eeg = butter(4, [low, high], btype='band')
        # ECG
        low, high = Config.ECG_BANDPASS[0] / nyq, Config.ECG_BANDPASS[1] / nyq
        self.b_ecg, self.a_ecg = butter(4, [low, high], btype='band')
        # EOG
        low, high = Config.EOG_BANDPASS[0] / nyq, Config.EOG_BANDPASS[1] / nyq
        self.b_eog, self.a_eog = butter(4, [low, high], btype='band')
        # Notch
        self.b_notch, self.a_notch = iirnotch(Config.NOTCH_FREQ, 30, self.sr)
    
    def _clean_signal(self, sig):
        nan_mask = np.isnan(sig)
        if np.any(nan_mask):
            valid_idx = np.where(~nan_mask)[0]
            if len(valid_idx) > 0:
                sig = np.interp(np.arange(len(sig)), valid_idx, sig[valid_idx])
            else:
                sig = np.zeros_like(sig)
        return detrend(sig, type='linear')
    
    def filter_eeg(self, eeg_data):
        filtered = np.zeros_like(eeg_data)
        for ch in range(eeg_data.shape[1]):
            sig = self._clean_signal(eeg_data[:, ch])
            sig = filtfilt(self.b_eeg, self.a_eeg, sig)
            sig = filtfilt(self.b_notch, self.a_notch, sig)
            filtered[:, ch] = sig
        return filtered
    
    def filter_ecg(self, ecg_data):
        sig = self._clean_signal(ecg_data)
        sig = filtfilt(self.b_ecg, self.a_ecg, sig)
        return filtfilt(self.b_notch, self.a_notch, sig)
    
    def filter_eog(self, eog_data):
        sig = self._clean_signal(eog_data)
        return filtfilt(self.b_eog, self.a_eog, sig)
    
    def bandpower(self, data, band):
        data = np.nan_to_num(data, nan=0.0)
        freqs, psd = welch(data, self.sr, nperseg=min(256, len(data)//2))
        idx = np.logical_and(freqs >= band[0], freqs <= band[1])
        return np.mean(psd[idx]) if np.any(idx) else 0
    
    def extract_hrv_from_ibi(self, ecg_filtered):
        features = {}
        if len(ecg_filtered) < self.sr * 2:
            return {'ibi_rmssd': 50, 'ibi_sdnn': 50, 'ibi_pnn50': 0,
                   'ibi_mean': 1000, 'ibi_cv': 0.1, 'ibi_count': 0}
        
        ecg_norm = zscore(ecg_filtered)
        peaks, _ = find_peaks(ecg_norm, height=1.0, distance=int(self.sr*0.4), prominence=0.5)
        features['ibi_count'] = len(peaks)
        
        if len(peaks) < 3:
            return {'ibi_rmssd': 50, 'ibi_sdnn': 50, 'ibi_pnn50': 0,
                   'ibi_mean': 1000, 'ibi_cv': 0.1, 'ibi_count': len(peaks)}
        
        rr_intervals = np.diff(peaks) / self.sr * 1000
        valid_rr = rr_intervals[(rr_intervals > 300) & (rr_intervals < 2000)]
        
        if len(valid_rr) < 3:
            valid_rr = rr_intervals
        
        features['ibi_mean'] = np.mean(valid_rr)
        features['ibi_sdnn'] = np.std(valid_rr)
        
        if len(valid_rr) > 1:
            rr_diff = np.diff(valid_rr)
            features['ibi_rmssd'] = np.sqrt(np.mean(rr_diff ** 2))
            nn50 = np.sum(np.abs(rr_diff) > 50)
            features['ibi_pnn50'] = (nn50 / len(rr_diff)) * 100 if len(rr_diff) > 0 else 0
            features['ibi_cv'] = features['ibi_sdnn'] / features['ibi_mean'] if features['ibi_mean'] > 0 else 0.1
        else:
            features.update({'ibi_rmssd': 50, 'ibi_pnn50': 0, 'ibi_cv': 0.1})
        
        # Add log-transformed HRV features (often more normal)
        features['ibi_rmssd_log'] = np.log1p(features['ibi_rmssd'])
        features['ibi_sdnn_log'] = np.log1p(features['ibi_sdnn'])
        
        return features
    
    def extract(self, eeg_win, npg_win):
        features = {}
        eeg_win = np.nan_to_num(eeg_win, nan=0.0)
        npg_win = np.nan_to_num(npg_win, nan=0.0)
        
        # Preprocess
        eeg_filtered = self.filter_eeg(eeg_win)
        ecg_filtered = self.filter_ecg(npg_win[:, 2])
        veog_filtered = self.filter_eog(npg_win[:, 0])
        
        F3, F4, P7, P8 = 2, 11, 5, 8
        
        # EEG Features
        features['frontal_theta'] = self.bandpower(eeg_filtered[:, F3], (4, 7))
        features['parietal_alpha'] = self.bandpower(eeg_filtered[:, P7], (8, 12))
        
        # Log-transformed ratio (better for skewed distributions)
        features['theta_alpha_ratio'] = features['frontal_theta'] / (features['parietal_alpha'] + 1e-10)
        features['theta_alpha_log'] = np.log1p(features['theta_alpha_ratio'])  # Key fix!
        
        # Frontal Asymmetry
        left_a = self.bandpower(eeg_filtered[:, F3], (8, 12))
        right_a = self.bandpower(eeg_filtered[:, F4], (8, 12))
        features['alpha_asymmetry'] = np.log(right_a + 1e-10) - np.log(left_a + 1e-10)
        
        # Beta features
        features['frontal_beta'] = self.bandpower(eeg_filtered[:, F3], (13, 30))
        features['theta_beta_ratio'] = features['frontal_theta'] / (features['frontal_beta'] + 1e-10)
        
        # HRV
        hrv_feat = self.extract_hrv_from_ibi(ecg_filtered)
        features.update(hrv_feat)
        
        # EOG
        veog = zscore(veog_filtered)
        blinks, _ = find_peaks(-veog, height=1.5, distance=int(self.sr*0.25))
        features['blink_rate'] = len(blinks) / 10 * 60
        
        # Quality metrics
        features['eeg_var'] = np.var(eeg_filtered)
        features['ecg_var'] = np.var(ecg_filtered)
        
        return features

# ==============================================================================
# MAIN PIPELINE - FIXED
# ==============================================================================
def main():
    print("=" * 70)
    print("MIND WANDERING DETECTION - FIXED PIPELINE")
    print("Fixes: Log-transform, StratifiedCV, Adaptive Thresholds, Regularization")
    print("=" * 70)
    
    # Load data
    print("\n[1/5] Loading data...")
    cache = np.load('sync_data_fixed.npz', allow_pickle=True)
    sync_data = {'eeg': cache['eeg'], 'npg': cache['npg'], 
                'time': cache['time'], 'sr': 128}
    
    behav = pd.read_csv(os.path.join(Config.DATA_DIR, '002_20260416_1335_behav.csv'))
    probe_data = behav[behav['Task'].isna()]
    focus_probes = probe_data[probe_data['Probe_Type'] == 'Focus'].copy()
    print(f"      Found {len(focus_probes)} probes")
    
    # Extract features
    print("\n[2/5] Extracting features...")
    extractor = MWFeatureExtractor(sr=128)
    features_list, labels_list = [], []
    
    session_duration = sync_data['time'][-1]
    probe_times = np.linspace(60, session_duration - 60, len(focus_probes))
    
    for i, (_, probe) in enumerate(focus_probes.iterrows()):
        if pd.isna(probe['Probe_Response']):
            continue
        
        label = 0 if probe['Probe_Response'] == 1 else 1
        probe_time = probe_times[min(i, len(probe_times)-1)]
        time_idx = np.argmin(np.abs(sync_data['time'] - probe_time))
        start = max(0, time_idx - int(Config.WINDOW_SEC * Config.TARGET_SR))
        end = time_idx
        
        if end - start < 5 * Config.TARGET_SR:
            continue
        
        try:
            feat = extractor.extract(sync_data['eeg'][start:end], 
                                    sync_data['npg'][start:end])
            features_list.append(feat)
            labels_list.append(label)
        except:
            continue
    
    print(f"      Samples: {len(features_list)} (Focused={np.sum(np.array(labels_list)==0)}, MW={np.sum(np.array(labels_list)==1)})")
    
    # Prepare data
    feature_names = list(features_list[0].keys())
    X = np.array([[f[k] for k in feature_names] for f in features_list])
    y = np.array(labels_list)
    
    # Remove infinite values
    X = np.nan_to_num(X, nan=np.nanmedian(X, axis=0), posinf=0, neginf=0)
    
    # ==============================================================================
    # ADAPTIVE THRESHOLD SETTING (Critical Fix!)
    # ==============================================================================
    ta_idx = feature_names.index('theta_alpha_ratio')
    ta_focused = X[y==0, ta_idx]
    ta_mw = X[y==1, ta_idx]
    
    # Set thresholds based on data distribution (25th/75th percentiles)
    Config.MW_THRESHOLD_LOW = np.percentile(ta_focused, 75)  # Upper range of focused
    Config.MW_THRESHOLD_HIGH = np.percentile(ta_mw, 25)      # Lower range of MW
    
    # Ensure they don't overlap too much
    if Config.MW_THRESHOLD_HIGH <= Config.MW_THRESHOLD_LOW:
        mid = (np.median(ta_focused) + np.median(ta_mw)) / 2
        Config.MW_THRESHOLD_LOW = mid * 0.9
        Config.MW_THRESHOLD_HIGH = mid * 1.1
    
    print(f"\n[3/5] Adaptive Thresholds Set:")
    print(f"      θ/α < {Config.MW_THRESHOLD_LOW:.2f}: Hard Focused")
    print(f"      θ/α > {Config.MW_THRESHOLD_HIGH:.2f}: Hard MW")
    print(f"      Middle: SVM Zone")
    
    # ==============================================================================
    # FEATURE SELECTION (Reduce overfitting)
    # ==============================================================================
    print("\n[4/5] Feature selection & model training...")
    
    # Select best k features (avoid overfitting with n=56)
    k = min(8, X.shape[1])  # Use 8 features max or all if less
    selector = SelectKBest(f_classif, k=k)
    X_selected = selector.fit_transform(X, y)
    selected_features = [feature_names[i] for i in selector.get_support(indices=True)]
    
    print(f"      Selected {k} features: {selected_features[:4]}...")
    
    # Scale
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X_selected)
    
    # ==============================================================================
    # CROSS-VALIDATION - StratifiedKFold instead of LOO
    # ==============================================================================
    # Use 5-fold Stratified (more stable than LOO with n=56)
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    
    # Linear SVM (less prone to overfitting than RBF with small data)
    svm = SVC(kernel='linear', C=0.5, probability=True, 
              class_weight='balanced', random_state=42)
    
    cv_scores = cross_val_score(svm, X_scaled, y, cv=cv, scoring='accuracy')
    
    print(f"\n      5-Fold CV Accuracy: {cv_scores.mean():.1%} (+/- {cv_scores.std():.1%})")
    
    # Train final on all data
    svm.fit(X_scaled, y)
    y_pred = svm.predict(X_scaled)
    y_proba = svm.predict_proba(X_scaled)[:, 1]
    
    # Metrics
    cm = confusion_matrix(y, y_pred)
    sensitivity = cm[1,1]/np.sum(y==1) if np.sum(y==1) > 0 else 0
    specificity = cm[0,0]/np.sum(y==0) if np.sum(y==0) > 0 else 0
    
    print(f"      Training Accuracy: {accuracy_score(y, y_pred):.1%}")
    print(f"      Sensitivity (MW): {sensitivity:.1%}")
    print(f"      Specificity (Focused): {specificity:.1%}")
    print(f"      AUC: {roc_auc_score(y, y_proba):.2f}")
    
    # Check for overfitting warning
    if accuracy_score(y, y_pred) - cv_scores.mean() > 0.15:
        print("      ⚠️ Warning: Possible overfitting (Train >> CV)")
    
    # ==============================================================================
    # VISUALIZATION - Fixed
    # ==============================================================================
    print("\n[5/5] Generating visualization...")
    
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle('Mind Wandering Detection - Fixed Model\n(Preprocessed + Log-features + Linear SVM)', 
                 fontsize=14, fontweight='bold')
    
    # Panel 1: Feature Importance (Linear SVM coefs)
    coefs = np.abs(svm.coef_[0])
    importance = pd.DataFrame({
        'feature': selected_features,
        'importance': coefs
    }).sort_values('importance', ascending=True).tail(6)
    
    colors = plt.cm.RdYlGn(np.linspace(0.3, 0.7, len(importance)))
    axes[0,0].barh(importance['feature'], importance['importance'], color=colors)
    axes[0,0].set_title('SVM Feature Weights (Linear)', fontweight='bold')
    axes[0,0].set_xlabel('Absolute Coefficient')
    
    # Panel 2: Theta/Alpha Distribution (Fixed bins)
    ta_idx = feature_names.index('theta_alpha_ratio')
    bins = np.linspace(min(X[:, ta_idx]), max(X[:, ta_idx]), 15)
    axes[0,1].hist(X[y==0, ta_idx], bins=bins, alpha=0.6, label='Focused', 
                  color='green', edgecolor='black')
    axes[0,1].hist(X[y==1, ta_idx], bins=bins, alpha=0.6, label='MW', 
                  color='red', edgecolor='black')
    axes[0,1].axvline(x=Config.MW_THRESHOLD_LOW, color='green', 
                     linestyle='--', linewidth=2, label=f'Safe Focused (<{Config.MW_THRESHOLD_LOW:.1f})')
    axes[0,1].axvline(x=Config.MW_THRESHOLD_HIGH, color='red', 
                     linestyle='--', linewidth=2, label=f'Safe MW (>{Config.MW_THRESHOLD_HIGH:.1f})')
    axes[0,1].set_xlabel('Theta/Alpha Ratio')
    axes[0,1].set_ylabel('Count')
    axes[0,1].set_title('θ/α Distribution with Adaptive Thresholds', fontweight='bold')
    axes[0,1].legend(loc='upper right', fontsize=8)
    
    # Panel 3: Confusion Matrix
    sns.heatmap(cm, annot=True, fmt='d', cmap='Blues', ax=axes[1,0],
               xticklabels=['Focused', 'MW'], yticklabels=['Focused', 'MW'],
               cbar_kws={'shrink': 0.8})
    axes[1,0].set_title(f'Confusion Matrix (CV Acc: {cv_scores.mean():.1%})', fontweight='bold')
    axes[1,0].set_ylabel('True Label')
    axes[1,0].set_xlabel('Predicted Label')
    
    # Panel 4: Safety Wrapper Zones (Actual data)
    axes[1,1].scatter(X[y==0, ta_idx], y_proba[y==0], alpha=0.7, 
                     label='Focused', color='green', s=100, edgecolors='black')
    axes[1,1].scatter(X[y==1, ta_idx], y_proba[y==1], alpha=0.7, 
                     label='MW', color='red', s=100, edgecolors='black')
    
    # Threshold lines
    axes[1,1].axvline(x=Config.MW_THRESHOLD_LOW, color='green', linestyle='--', alpha=0.7, linewidth=2)
    axes[1,1].axvline(x=Config.MW_THRESHOLD_HIGH, color='red', linestyle='--', alpha=0.7, linewidth=2)
    axes[1,1].axhline(y=0.5, color='blue', linestyle='--', alpha=0.5)
    
    # Shade zones
    axes[1,1].axvspan(0, Config.MW_THRESHOLD_LOW, alpha=0.2, color='green', label='Hard Focused')
    axes[1,1].axvspan(Config.MW_THRESHOLD_HIGH, max(X[:, ta_idx])*1.1, alpha=0.2, color='red', label='Hard MW')
    
    axes[1,1].set_xlabel('Theta/Alpha Ratio')
    axes[1,1].set_ylabel('SVM Probability (MW)')
    axes[1,1].set_title('Safety Wrapper with Real Thresholds', fontweight='bold')
    axes[1,1].legend(loc='center right')
    axes[1,1].set_ylim(-0.05, 1.05)
    
    plt.tight_layout(rect=[0, 0.03, 1, 0.95])
    plt.savefig(Config.PLOT_FILE, dpi=300, bbox_inches='tight')
    print(f"      ✓ Saved to {Config.PLOT_FILE}")
    plt.show()
    
    # Save model
    with open('mw_model_fixed.pkl', 'wb') as f:
        pickle.dump({
            'model': svm,
            'scaler': scaler,
            'features': selected_features,
            'selector': selector,
            'thresholds': {
                'low': Config.MW_THRESHOLD_LOW,
                'high': Config.MW_THRESHOLD_HIGH
            },
            'cv_accuracy': cv_scores.mean(),
            'cv_std': cv_scores.std()
        }, f)
    
    print(f"\n{'='*70}")
    print("SUMMARY OF FIXES:")
    print(f"1. Adaptive thresholds: [{Config.MW_THRESHOLD_LOW:.2f}, {Config.MW_THRESHOLD_HIGH:.2f}]")
    print(f"2. Used Linear SVM (RBF was overfitting)")
    print(f"3. Feature selection: {k} best features")
    print(f"4. Log-transformed θ/α ratio")
    print(f"5. 5-Fold CV instead of LOO (more stable)")
    print(f"{'='*70}")

if __name__ == "__main__":
    main()
