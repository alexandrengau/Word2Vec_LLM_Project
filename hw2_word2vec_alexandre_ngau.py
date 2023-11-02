# -*- coding: utf-8 -*-
"""hw2_word2vec_alexandre_ngau.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1yuC0qGOIY4tgQv0zWg-piTIGFg6BHRvL

# Alexandre NGAU
"""

# Commented out IPython magic to ensure Python compatibility.
# """
# %%capture
# !pip install transformers datasets
# """

import numpy as np
import torch
import torch.nn.functional as F
import torch.nn as nn
import math
import random
from torch.utils.data import DataLoader
from tabulate import tabulate
from datasets import load_dataset

from tqdm import trange
from tqdm import tqdm
from transformers import BertTokenizer

DEVICE = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
print(DEVICE)

# Global variables

R = 4
K = 6
batch_size = 16
n_epochs = 10

"""First cells will be the same than the ones of the lab on text convolution.

# Data loading

"""

dataset = load_dataset("scikit-learn/imdb", split="train")

"""# Pre-processing / Tokenization

This is a very important step. It may be boring but very important. In this session we will be lazy, but in real life, the time spent on inspecting and cleaning data is never wasted. It is true for text, but also for everything.



In PyTorch, everything is tensor. Words are replaced by indices. A sentence, is therefore a sequence of indices (long integers). In the first HW, you constructed a `WhiteSpaceTokenizer`. Here we will use an already built tokenizer. It is more appropriate to transformers. It relies on sub-word units, and converts everything in lower case. This is not always the best choice, but here it will be sufficient. To quote the documentation, this tokenizer allows you to:
- Tokenize (splitting strings in sub-word token strings), convert tokens strings to ids and back, and encoding/decoding (i.e., tokenizing and converting to integers).
- Add new tokens to the vocabulary in a way that is independent of the underlying structure (BPE, SentencePiece…).
- Manage special tokens (like mask, beginning-of-sentence, etc.): adding them, assigning them to attributes in the tokenizer for easy access and making sure they are not split during tokenization.

Here we are going to use the tokenizer from the well known Bert model, that we can directly download.
"""

tokenizer = BertTokenizer.from_pretrained("bert-base-uncased", do_lower_case=True)

def preprocessing_fn(x, tokenizer):
    x["review_ids"] = tokenizer(
        x["review"],
        add_special_tokens=False,
        truncation=True,
        max_length=256,
        padding=False,
        return_attention_mask=False,
    )["input_ids"]
    x["label"] = 0 if x["sentiment"] == "negative" else 1
    return x

"""Same cell than in the lab session.

🚧 **TODO** 🚧

Read the documentation about HuggingFace dataset and complete the code below.
You should:
- Shuffle the dataset
- For computational reasons, use only a total of **5000 samples**.
- Tokenize the dataset with the `preprocessing_fn`. (*Hint: use the `Dataset.map` method from HuggingFace*).
- Keep only columns `review_ids` and `label`.
- Make a train/validation split, (**80% / 20%**). Call these dataset `train_set` and `valid_set`.

"""

n_samples = 50  # the number of training example

# We first shuffle the data !
dataset = dataset.shuffle()

# Select 5000 samples
split_dataset = dataset.select(range(n_samples))

# Tokenize the dataset
tok_dataset = split_dataset.map(preprocessing_fn,
                                fn_kwargs={"tokenizer": tokenizer})

# Remove useless columns
tok_dataset = tok_dataset.select_columns(["review_ids", "label"])

# Split the train and validation
tok_dataset = tok_dataset.train_test_split(test_size=0.2)

document_train_set = tok_dataset["train"]
document_valid_set = tok_dataset["test"]


def extract_words_contexts(list_of_ids_of_txt_doc, R=R):
  w_ids = list_of_ids_of_txt_doc
  c_plus_ids = []
  for w in range(len(w_ids)) :
    c_plus = []
    for r in range(w-R, w+R+1):
      if r < 0 :
        c_plus.append(0)
      if r >= 0 and r < len(w_ids) and r != w:
        c_plus.append(w_ids[r])
      if r >= len(w_ids):
        c_plus.append(0)
    c_plus_ids.append(c_plus)
  return w_ids, c_plus_ids

w_test, c_test = extract_words_contexts(document_train_set[0]["review_ids"])
etalon = len(c_test[0])
for i in c_test:
  assert len(i) == etalon

def flatten_dataset_to_list(data_set, R=R):
  W = []
  C = []
  for i in range(len(data_set)):
    w, c = extract_words_contexts(data_set[i]["review_ids"])
    W += w
    C += c
  return W, C

flatten_document_train_set = flatten_dataset_to_list(document_train_set)
flatten_document_valid_set = flatten_dataset_to_list(document_valid_set)

from torch.utils.data import Dataset


class set(Dataset):
    def __init__(self, flatten_document_set):
        self.word = flatten_document_set[0]
        self.positive_context = flatten_document_set[1]

    def __len__(self):
        return len(self.word)

    def __getitem__(self, idx: int):
        word = self.word[idx]
        positive_context = self.positive_context[idx]
        return word, positive_context

train_set = set(flatten_document_train_set)
valid_set = set(flatten_document_valid_set)


def collate_fn(batch, R=R, K=K):
  dict = {}
  word_id = []
  positive_context_ids = []
  negative_context_ids = []
  for i in range(len(batch)):
    word_id.append(batch[i][0])
    positive_context_ids.append(batch[i][1])
    negative_context_ids.append(random.sample(list(tokenizer.get_vocab().values()), 2*K*R))
  dict["word_id"] = torch.tensor(word_id)
  dict["positive_context_ids"] = torch.tensor(positive_context_ids)
  dict["negative_context_ids"] = torch.tensor(negative_context_ids)
  return dict

from torch.utils.data import DataLoader
"""
for batch_size in range(1,3):
  dataloader = DataLoader(
      dataset=train_set, batch_size=batch_size, collate_fn=collate_fn
      )
  for batch in dataloader:
    print(f"R={R}",
          f"K={K}",
          f"word_id tensor shape = {batch['word_id'].shape}",
          f"positive_context_ids tensor shape = {batch['positive_context_ids'].shape}",
          f"negative_context_ids tensor shape = {batch['negative_context_ids'].shape}"
         )
    break
  """

class Word2Vec(nn.Module):
  def __init__(self, vocab_size, embedding_dimension):
    super().__init__()
    self.embedding_words = nn.Embedding(vocab_size, embedding_dimension)
    self.embedding_context = nn.Embedding(vocab_size, embedding_dimension)

  def forward(self, target_word_ids, context_word_ids):
    embedded_target = self.embedding_words(target_word_ids)
    embedded_context = self.embedding_context(context_word_ids)

    score = torch.sigmoid(torch.sum(embedded_context*embedded_target, dim=2))
    return score

def validation(model, valid_dataloader):
    total_size = 0
    acc_total = 0
    loss_total = 0
    criterion = nn.BCELoss(reduction = 'none')
    model.eval()
    # model = model.to(DEVICE)
    with torch.no_grad():
        for batch in tqdm(valid_dataloader):
            # batch = {k: v.to(DEVICE) for k, v in batch.items()}
            word_id = batch["word_id"].to(DEVICE)
            positive_context_ids = batch["positive_context_ids"].to(DEVICE)
            negative_context_ids = batch["negative_context_ids"].to(DEVICE)
            pred_pos = model(word_id.unsqueeze(1), positive_context_ids)
            pred_neg = model(word_id.unsqueeze(1), negative_context_ids)
            loss_positive = torch.mean(criterion(pred_pos, torch.ones(pred_pos.shape, device=DEVICE)), dim=1)
            loss_negative = torch.mean(criterion(pred_neg, torch.zeros(pred_neg.shape, device=DEVICE)), dim=1)
            loss = torch.mean(loss_positive + loss_negative)
            loss_total += loss.detach().cpu().item()
            acc_positive = (pred_pos.squeeze() > 0.5)
            acc_negative = (pred_neg.squeeze() < 0.5)
            acc_total += acc_positive.int().sum().item()
            acc_total += acc_negative.int().sum().item()
            total_size += acc_positive.numel()
            total_size += acc_negative.numel()
    model.train()
    return loss_total / len(valid_dataloader), acc_total / total_size

def training(model, batch_size, n_epochs, lr=5e-5):
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=lr,
        eps=1e-08,
    )

    train_dataloader = DataLoader(
        train_set, batch_size=batch_size, collate_fn=collate_fn
        )
    valid_dataloader = DataLoader(
        valid_set, batch_size=batch_size, collate_fn=collate_fn
        )

    list_val_acc = []
    list_train_acc = []
    list_train_loss = []
    list_val_loss = []
    criterion = nn.BCELoss(reduction = 'none')
    for e in range(n_epochs):
        # ========== Training ==========

        # Set model to training mode
        model.train()
        # model = model.to(DEVICE)

        # Tracking variables
        train_loss = 0
        epoch_train_acc = 0
        total_size = 0
        for batch in tqdm(train_dataloader):
            # batch = {k: v.to(DEVICE) for k, v in batch.items()}
            word_id, positive_context_ids, negative_context_ids = (
                batch["word_id"].to(DEVICE),
                batch["positive_context_ids"].to(DEVICE),
                batch["negative_context_ids"].to(DEVICE),
            )
            optimizer.zero_grad()
            # Forward pass
            output_positive = model(word_id.unsqueeze(1), positive_context_ids)
            output_negative = model(word_id.unsqueeze(1), negative_context_ids)
            # Backward pass
            loss_positive = torch.mean(criterion(output_positive, torch.ones(output_positive.shape, device=DEVICE)), dim=1)
            loss_negative = torch.mean(criterion(output_negative, torch.zeros(output_negative.shape, device=DEVICE)), dim=1)
            print(f"loss positive = {loss_positive}")
            loss = loss_positive.item() + loss_negative.item()
            loss.backward()
            optimizer.step()
            train_loss += loss.detach().cpu().item()
            acc_positive = (output_positive.squeeze() > 0.5)
            acc_negative = (output_negative.squeeze() < 0.5)
            epoch_train_acc += acc_positive.int().sum().item()
            epoch_train_acc += acc_negative.int().sum().item()
            total_size += acc_positive.numel()
            total_size += acc_negative.numel()
        list_train_acc.append(epoch_train_acc / total_size)
        list_train_loss.append(train_loss / len(train_dataloader))

        # ========== Validation ==========

        l, a = validation(model, valid_dataloader)
        list_val_loss.append(l)
        list_val_acc.append(a)
        print(
            e,
            "\n\t - Train loss: {:.4f}".format(list_train_loss[-1]),
            "Train acc: {:.4f}".format(list_train_acc[-1]),
            "Val loss: {:.4f}".format(l),
            "Val acc:{:.4f}".format(a),
        )
    return list_train_loss, list_train_acc, list_val_loss, list_val_acc

embedding_dimension = 100
vocab_size = len(tokenizer.get_vocab())
model = Word2Vec(vocab_size, embedding_dimension)
model = model.to(DEVICE)

training(model, batch_size, n_epochs)

def save_model(model, file_path, n_samples=n_samples, dimension=embedding_dimension, radius=R, ratio=K, batch=batch_size, epoch=nb_epochs):
    file_name = f"model_sample-{n_samples}_dim-{dimension}_radius-{radius}_ratio-{ratio}-batch-{batch}-epoch-{epoch}.ckpt"
    torch.save(model.state_dict(), file_path + file_name)

PATH = '~/llm_hw2/model_data/'
save_model(model, file_path=PATH, n_samples=n_samples, dimension=embedding_dimension, radius=R, ratio=K, batch=batch_size, epoch=nb_epochs)

