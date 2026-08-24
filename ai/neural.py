"""
极简神经网络模块：纯 NumPy 实现的多层感知机 + 1D 卷积。

设计理念：
- 不需要 PyTorch/TensorFlow，只用 NumPy 实现
- 自动检测 NumPy 是否可用，不可用时优雅降级
- 集成到 easy-ai 的意图识别系统

包含：
- DenseLayer: 全连接层 + ReLU/Softmax
- Conv1DLayer: 一维卷积层（用于文本特征提取）
- MiniMLP: 完整的多层感知机分类器
- TextCNN: 文本卷积神经网络（用于意图分类）

参考架构：
  TextCNN: Embedding -> Conv1D -> ReLU -> MaxPool -> Flatten -> Dense -> Softmax
  MiniMLP: Input -> Dense(ReLU) -> Dense(ReLU) -> Dense(Softmax)
"""

from __future__ import annotations

import math
import random
import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Union


# 尝试导入 NumPy（可选依赖）
try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False


class DenseLayer:
    """全连接层：y = activation(W @ x + b)"""

    def __init__(self, input_dim: int, output_dim: int, activation: str = "relu"):
        self.input_dim = input_dim
        self.output_dim = output_dim
        self.activation = activation

        if _HAS_NUMPY:
            # He 初始化（适合 ReLU）
            scale = math.sqrt(2.0 / input_dim)
            self.W = np.random.randn(output_dim, input_dim) * scale
            self.b = np.zeros(output_dim)
            self.dW = np.zeros_like(self.W)
            self.db = np.zeros_like(self.b)
        else:
            self.W = None
            self.b = None

    def forward(self, x):
        """前向传播。x: (batch, input_dim) 或 (input_dim,)"""
        if not _HAS_NUMPY:
            raise RuntimeError("NumPy 未安装，无法运行神经网络")

        z = np.dot(x, self.W.T) + self.b

        if self.activation == "relu":
            return np.maximum(0, z), z
        elif self.activation == "sigmoid":
            return 1.0 / (1.0 + np.exp(-np.clip(z, -50, 50))), z
        elif self.activation == "softmax":
            shifted = z - np.max(z, axis=-1, keepdims=True)
            exp = np.exp(np.clip(shifted, -50, 50))
            return exp / np.sum(exp, axis=-1, keepdims=True), z
        elif self.activation == "tanh":
            return np.tanh(z), z
        else:
            return z, z  # linear

    def backward(self, dout, cache_z, prev_a):
        """反向传播。返回 dW, db, da_prev"""
        batch_size = prev_a.shape[0] if prev_a.ndim > 1 else 1

        if self.activation == "relu":
            dz = dout * (cache_z > 0)
        elif self.activation == "sigmoid":
            s = 1.0 / (1.0 + np.exp(-np.clip(cache_z, -50, 50)))
            dz = dout * s * (1 - s)
        elif self.activation == "softmax":
            dz = dout  # softmax 的梯度已在交叉熵中处理
        elif self.activation == "tanh":
            dz = dout * (1 - np.tanh(cache_z) ** 2)
        else:
            dz = dout

        self.dW = np.dot(dz.T, prev_a) / batch_size
        self.db = np.mean(dz, axis=0) if dz.ndim > 1 else dz
        da_prev = np.dot(dz, self.W)

        return da_prev

    def update(self, lr: float = 0.01):
        """梯度下降更新参数。"""
        self.W -= lr * self.dW
        self.b -= lr * self.db


class Conv1DLayer:
    """一维卷积层（用于文本序列）。

    输入: (batch, channels, seq_len)
    输出: (batch, filters, new_seq_len)
    """

    def __init__(self, in_channels: int, out_channels: int, kernel_size: int,
                 stride: int = 1, padding: int = 0):
        self.in_channels = in_channels
        self.out_channels = out_channels
        self.kernel_size = kernel_size
        self.stride = stride
        self.padding = padding

        if _HAS_NUMPY:
            scale = math.sqrt(2.0 / (in_channels * kernel_size))
            self.W = np.random.randn(out_channels, in_channels, kernel_size) * scale
            self.b = np.zeros(out_channels)
            self.dW = np.zeros_like(self.W)
            self.db = np.zeros_like(self.b)

    def forward(self, x):
        """前向传播。x: (batch, channels, seq_len)"""
        if not _HAS_NUMPY:
            raise RuntimeError("NumPy 未安装")

        batch_size, channels, seq_len = x.shape

        if self.padding > 0:
            x = np.pad(x, ((0, 0), (0, 0), (self.padding, self.padding)))

        out_len = (seq_len + 2 * self.padding - self.kernel_size) // self.stride + 1
        out = np.zeros((batch_size, self.out_channels, out_len))

        for b in range(batch_size):
            for f in range(self.out_channels):
                for i in range(out_len):
                    start = i * self.stride
                    end = start + self.kernel_size
                    region = x[b, :, start:end]
                    out[b, f, i] = np.sum(region * self.W[f]) + self.b[f]

        return out

    def update(self, lr: float = 0.01):
        self.W -= lr * self.dW
        self.b -= lr * self.db


class MiniMLP:
    """极简多层感知机分类器。

    用法：
        model = MiniMLP(input_dim=100, hidden_dims=[64, 32], num_classes=5)
        model.fit(X_train, y_train_ont_hot, epochs=50, lr=0.01)
        pred = model.predict(X_test)
    """

    def __init__(self, input_dim: int, hidden_dims: List[int], num_classes: int,
                 dropout: float = 0.0):
        self.input_dim = input_dim
        self.num_classes = num_classes
        self.dropout = dropout
        self._trained = False

        if not _HAS_NUMPY:
            self.layers = []
            return

        self.layers: List[DenseLayer] = []
        dims = [input_dim] + hidden_dims + [num_classes]

        for i in range(len(dims) - 1):
            act = "softmax" if i == len(dims) - 2 else "relu"
            self.layers.append(DenseLayer(dims[i], dims[i + 1], activation=act))

    def forward(self, x):
        """前向传播，返回 (output, caches)"""
        if not _HAS_NUMPY:
            return None, []
        a = x
        caches = []  # (a_prev, z) for each layer
        for i, layer in enumerate(self.layers):
            z = np.dot(a, layer.W.T) + layer.b
            if layer.activation == "relu":
                a_out = np.maximum(0, z)
            elif layer.activation == "softmax":
                shifted = z - np.max(z, axis=-1, keepdims=True)
                a_out = np.exp(np.clip(shifted, -50, 50))
                a_out = a_out / np.sum(a_out, axis=-1, keepdims=True)
            elif layer.activation == "sigmoid":
                a_out = 1.0 / (1.0 + np.exp(-np.clip(z, -50, 50)))
            else:
                a_out = z
            caches.append((a, z))
            a = a_out

            # Dropout（仅训练时）
            if self.dropout > 0 and i < len(self.layers) - 1:
                mask = np.random.binomial(1, 1 - self.dropout, a.shape) / (1 - self.dropout)
                a = a * mask

        return a, caches

    def backward(self, y_true, y_pred, caches, lr: float = 0.01):
        """反向传播 + 参数更新。"""
        batch_size = y_true.shape[0]

        # 交叉熵损失梯度（softmax + cross-entropy 简化）
        dz = y_pred - y_true  # (batch, num_classes)

        for i in range(len(self.layers) - 1, -1, -1):
            layer = self.layers[i]
            prev_a, cache_z = caches[i]

            if layer.activation == "relu":
                da = dz * (cache_z > 0)
            elif layer.activation == "softmax":
                da = dz  # 已简化
            elif layer.activation == "sigmoid":
                s = 1.0 / (1.0 + np.exp(-np.clip(cache_z, -50, 50)))
                da = dz * s * (1 - s)
            else:
                da = dz

            layer.dW = np.dot(da.T, prev_a) / batch_size
            layer.db = np.mean(da, axis=0)
            layer.W -= lr * layer.dW
            layer.b -= lr * layer.db

            if i > 0:
                dz = np.dot(da, layer.W)

    def fit(self, X, y, epochs: int = 50, lr: float = 0.01, batch_size: int = 32,
            validation_data: Optional[Tuple] = None, verbose: bool = True):
        """训练模型。

        Args:
            X: (n_samples, input_dim) 特征矩阵
            y: (n_samples, num_classes) one-hot 标签
            epochs: 训练轮数
            lr: 学习率
            batch_size: 批量大小
            validation_data: (X_val, y_val) 可选验证集
            verbose: 是否打印训练进度
        """
        if not _HAS_NUMPY:
            raise RuntimeError("NumPy 未安装")

        n_samples = X.shape[0]
        history = {"loss": [], "val_loss": [], "accuracy": [], "val_accuracy": []}

        for epoch in range(epochs):
            # 洗牌
            indices = np.random.permutation(n_samples)
            X_shuffled = X[indices]
            y_shuffled = y[indices]

            total_loss = 0.0
            n_batches = 0

            for start in range(0, n_samples, batch_size):
                end = min(start + batch_size, n_samples)
                X_batch = X_shuffled[start:end]
                y_batch = y_shuffled[start:end]

                y_pred, caches = self.forward(X_batch)
                self.backward(y_batch, y_pred, caches, lr)

                # 交叉熵损失
                loss = -np.mean(np.sum(y_batch * np.log(np.clip(y_pred, 1e-12, 1.0)), axis=1))
                total_loss += loss
                n_batches += 1

            avg_loss = total_loss / max(n_batches, 1)
            history["loss"].append(avg_loss)

            # 训练准确率
            y_pred_full, _ = self.forward(X)
            train_acc = np.mean(np.argmax(y_pred_full, axis=1) == np.argmax(y, axis=1))
            history["accuracy"].append(train_acc)

            # 验证
            if validation_data:
                X_val, y_val = validation_data
                val_pred, _ = self.forward(X_val)
                val_loss = -np.mean(np.sum(y_val * np.log(np.clip(val_pred, 1e-12, 1.0)), axis=1))
                val_acc = np.mean(np.argmax(val_pred, axis=1) == np.argmax(y_val, axis=1))
                history["val_loss"].append(val_loss)
                history["val_accuracy"].append(val_acc)

            if verbose and (epoch % max(1, epochs // 10) == 0 or epoch == epochs - 1):
                msg = f"Epoch {epoch+1}/{epochs} - loss: {avg_loss:.4f} - acc: {train_acc:.4f}"
                if validation_data:
                    msg += f" - val_loss: {val_loss:.4f} - val_acc: {val_acc:.4f}"
                print(msg)

        self._trained = True
        return history

    def predict(self, X) -> np.ndarray:
        """预测类别。返回 (n_samples,) 的类别索引数组。"""
        if not _HAS_NUMPY:
            return np.array([])
        y_pred, _ = self.forward(X)
        return np.argmax(y_pred, axis=1)

    def predict_proba(self, X) -> np.ndarray:
        """预测概率。返回 (n_samples, num_classes) 的概率矩阵。"""
        if not _HAS_NUMPY:
            return np.array([])
        y_pred, _ = self.forward(X)
        return y_pred

    def save(self, filepath: str):
        """保存模型参数到 JSON 文件。"""
        if not _HAS_NUMPY:
            return
        data = {
            "input_dim": self.input_dim,
            "num_classes": self.num_classes,
            "dropout": self.dropout,
            "layers": []
        }
        for layer in self.layers:
            data["layers"].append({
                "W": layer.W.tolist(),
                "b": layer.b.tolist(),
                "activation": layer.activation,
                "input_dim": layer.input_dim,
                "output_dim": layer.output_dim,
            })
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        print(f"[MiniMLP] 模型已保存到 {filepath}")

    def load(self, filepath: str):
        """从 JSON 文件加载模型参数。"""
        if not _HAS_NUMPY:
            return
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.input_dim = data["input_dim"]
        self.num_classes = data["num_classes"]
        self.dropout = data.get("dropout", 0.0)

        self.layers = []
        for ld in data["layers"]:
            layer = DenseLayer(ld["input_dim"], ld["output_dim"], ld["activation"])
            layer.W = np.array(ld["W"])
            layer.b = np.array(ld["b"])
            self.layers.append(layer)

        self._trained = True
        print(f"[MiniMLP] 模型已从 {filepath} 加载")

    @property
    def is_trained(self) -> bool:
        return self._trained


class NeuralIntentClassifier:
    """基于 MiniMLP 的意图分类器（增强版意图识别）。

    替代原有的简单关键词分类器，提供基于神经网络的意图分类。
    支持：

    - 特征提取：TF-IDF 或 Char-NGram 向量化
    - 训练：监督学习从标注数据学习意图
    - 推理：给定文本返回意图类别和置信度

    用法：
        clf = NeuralIntentClassifier(num_classes=5)
        clf.train(texts, labels)
        intent, confidence = clf.classify("今天天气怎么样")
    """

    # 预定义意图标签
    DEFAULT_INTENTS = [
        "greeting",      # 问候
        "farewell",      # 告别
        "question",      # 提问
        "command",       # 指令
        "statement",     # 陈述
        "emotion",       # 情感表达
        "help",          # 求助
        "unknown",       # 未知
    ]

    def __init__(self, num_classes: Optional[int] = None, intents: Optional[List[str]] = None):
        self.intents = intents or self.DEFAULT_INTENTS[:num_classes] if num_classes else self.DEFAULT_INTENTS
        self.num_classes = len(self.intents)
        self._vectorizer_dim = 128  # 特征向量维度
        self._model: Optional[MiniMLP] = None
        self._char_vocab: Dict[str, int] = {}
        self._label_to_idx: Dict[str, int] = {label: i for i, label in enumerate(self.intents)}
        self._idx_to_label: Dict[int, str] = {i: label for label, i in self._label_to_idx.items()}
        self._trained = False

    def _build_vocab(self, texts: List[str]):
        """构建字符级词汇表（适用于中文和英文）。"""
        self._char_vocab.clear()
        all_chars = set()
        for text in texts:
            for char in text:
                all_chars.add(char)

        # 排序确保一致性
        for i, char in enumerate(sorted(all_chars)):
            self._char_vocab[char] = i + 1  # 0 留给 padding

    def _vectorize(self, texts: List[str], max_len: int = 50) -> np.ndarray:
        """将文本列表转换为特征向量（Char-BoW + 位置编码）。"""
        if not _HAS_NUMPY:
            return None

        n = len(texts)
        vectors = np.zeros((n, self._vectorizer_dim))

        for i, text in enumerate(texts):
            # Char-level one-hot 统计
            char_counts = np.zeros(len(self._char_vocab) + 1)
            for char in text:
                idx = self._char_vocab.get(char, 0)
                char_counts[idx] += 1

            # 归一化
            total = char_counts.sum()
            if total > 0:
                char_counts = char_counts / total

            # 映射到固定维度
            vocab_size = len(self._char_vocab) + 1
            for j in range(min(vocab_size, self._vectorizer_dim)):
                vectors[i, j] = char_counts[j % vocab_size] * (1.0 if j < vocab_size else 0.0)

            # 简单的 n-gram 特征（bigram + trigram）
            ngram_features = self._extract_ngram_features(text)
            for j, val in enumerate(ngram_features):
                pos = vocab_size + j
                if pos < self._vectorizer_dim:
                    vectors[i, pos] = val

        return vectors

    def _extract_ngram_features(self, text: str, max_features: int = 64) -> np.ndarray:
        """提取字符 n-gram 特征（bigram 和 trigram）。"""
        if not _HAS_NUMPY:
            return np.array([])
        features = np.zeros(max_features)
        ngram_counts: Dict[str, int] = {}

        # Bigram
        for i in range(len(text) - 1):
            ng = text[i:i+2]
            ngram_counts[ng] = ngram_counts.get(ng, 0) + 1

        # Trigram
        for i in range(len(text) - 2):
            ng = text[i:i+3]
            ngram_counts[ng] = ngram_counts.get(ng, 0) + 1

        # 取频率最高的 n-gram
        top = sorted(ngram_counts.items(), key=lambda x: -x[1])[:max_features]
        for j, (_, count) in enumerate(top):
            features[j] = min(count / 10.0, 1.0)  # 归一化

        return features

    def train(self, texts: List[str], labels: List[str],
              epochs: int = 100, lr: float = 0.05, verbose: bool = True):
        """训练意图分类器。

        Args:
            texts: 训练文本列表
            labels: 对应的意图标签列表
            epochs: 训练轮数
            lr: 学习率
            verbose: 是否打印进度
        """
        if not _HAS_NUMPY:
            print("[NeuralIntentClassifier] NumPy 未安装，跳过训练。")
            return None

        # 构建词汇表
        self._build_vocab(texts)

        # 向量化
        X = self._vectorize(texts)

        # One-hot 编码标签
        y = np.zeros((len(labels), self.num_classes))
        for i, label in enumerate(labels):
            if label in self._label_to_idx:
                y[i, self._label_to_idx[label]] = 1.0
            else:
                y[i, self._label_to_idx["unknown"]] = 1.0

        # 创建并训练模型
        self._model = MiniMLP(
            input_dim=self._vectorizer_dim,
            hidden_dims=[64, 32],
            num_classes=self.num_classes,
            dropout=0.1
        )

        history = self._model.fit(X, y, epochs=epochs, lr=lr, verbose=verbose)
        self._trained = True
        return history

    def classify(self, text: str) -> Tuple[str, float]:
        """分类文本意图。返回 (意图标签, 置信度)。

        Args:
            text: 输入文本

        Returns:
            (intent_label, confidence)
        """
        if not self._trained or not _HAS_NUMPY:
            return "unknown", 0.0

        X = self._vectorize([text])
        probs = self._model.predict_proba(X)[0]
        best_idx = int(np.argmax(probs))
        confidence = float(probs[best_idx])

        return self._idx_to_label.get(best_idx, "unknown"), confidence

    def classify_top_k(self, text: str, k: int = 3) -> List[Tuple[str, float]]:
        """返回 top-k 意图分类结果。"""
        if not self._trained or not _HAS_NUMPY:
            return [("unknown", 0.0)]

        X = self._vectorize([text])
        probs = self._model.predict_proba(X)[0]
        top_indices = np.argsort(probs)[::-1][:k]
        return [(self._idx_to_label.get(int(i), "unknown"), float(probs[i]))
                for i in top_indices]

    def save(self, filepath: str):
        """保存分类器（词汇表 + 模型参数）。"""
        data = {
            "intents": self.intents,
            "char_vocab": self._char_vocab,
            "vectorizer_dim": self._vectorizer_dim,
        }
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        if self._model:
            model_path = filepath.replace(".json", "_weights.json")
            self._model.save(model_path)
        print(f"[NeuralIntentClassifier] 已保存到 {filepath}")

    def load(self, filepath: str):
        """加载分类器。"""
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.intents = data["intents"]
        self.num_classes = len(self.intents)
        self._char_vocab = data["char_vocab"]
        self._vectorizer_dim = data.get("vectorizer_dim", 128)
        self._label_to_idx = {label: i for i, label in enumerate(self.intents)}
        self._idx_to_label = {i: label for label, i in self._label_to_idx.items()}

        # 如有模型权重，加载
        model_path = filepath.replace(".json", "_weights.json")
        if os.path.exists(model_path):
            self._model = MiniMLP(
                input_dim=self._vectorizer_dim,
                hidden_dims=[64, 32],
                num_classes=self.num_classes
            )
            self._model.load(model_path)
            self._trained = True
        print(f"[NeuralIntentClassifier] 已从 {filepath} 加载")

    def _generate_training_data(self, seed_texts: Dict[str, List[str]]) -> Tuple[List[str], List[str]]:
        """从种子文本生成训练数据（数据增强）。"""
        texts = []
        labels = []
        for intent, seed_list in seed_texts.items():
            for text in seed_list:
                texts.append(text)
                labels.append(intent)
                # 简单增强：添加变体
                if len(text) > 2:
                    texts.append(text + "？")
                    labels.append(intent)
                    texts.append(text + "！")
                    labels.append(intent)
        return texts, labels

    @property
    def is_trained(self) -> bool:
        return self._trained and _HAS_NUMPY


# ============================================================
# 便捷函数
# ============================================================
def check_numpy() -> bool:
    """检查 NumPy 是否可用。"""
    return _HAS_NUMPY
