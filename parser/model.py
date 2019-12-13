# -*- coding: utf-8 -*-

from parser.metric import Metric

import torch
import torch.nn as nn


class Model(object):

    def __init__(self, config, vocab, parser):
        super(Model, self).__init__()

        self.config = config
        self.vocab = vocab
        self.parser = parser
        self.criterion = nn.CrossEntropyLoss()

    def train(self, loader):
        self.parser.train()

        for words, chars, arcs, rels, tasks in loader:
            self.optimizer.zero_grad()

            mask = words.ne(self.vocab.pad_index)
            # ignore the first token of each sentence
            mask[:, 0] = 0
            partial_mask = arcs.ne(-1)
            mask = mask & partial_mask
            s_arcs, s_rels = self.parser(words, chars, tasks)

            loss = 0
            for i, (s_arc, s_rel) in enumerate(zip(s_arcs, s_rels)):
                if s_arc is None and s_rel is None:
                    continue
                task_mask = tasks.eq(i)
                s_arc, s_rel = s_arc[mask[task_mask]], s_rel[mask[task_mask]]
                if len(s_arc) > 0:
                    gold_arc, gold_rel = arcs[task_mask][mask[task_mask]
                                                        ], rels[task_mask][mask[task_mask]]
                    loss += self.get_loss(s_arc, s_rel, gold_arc, gold_rel)

            loss.backward()
            nn.utils.clip_grad_norm_(self.parser.parameters(),
                                     self.config.clip)
            self.optimizer.step()
            self.scheduler.step()

    @torch.no_grad()
    def evaluate(self, loader, punct=False):
        self.parser.eval()

        loss, metric = 0, Metric()

        for words, chars, arcs, rels, tasks in loader:
            mask = words.ne(self.vocab.pad_index)
            # ignore the first token of each sentence
            mask[:, 0] = 0
            partial_mask = arcs.ne(-1)
            mask = mask & partial_mask
            # ignore all punctuation if not specified
            if not punct:
                puncts = words.new_tensor(self.vocab.puncts)
                mask &= words.unsqueeze(-1).ne(puncts).all(-1)

            s_arcs, s_rels = self.parser(words, chars, tasks)
            for i, (s_arc, s_rel) in enumerate(zip(s_arcs, s_rels)):
                if s_arc is None and s_rel is None:
                    continue
                task_mask = tasks.eq(i)
                s_arc, s_rel = s_arc[mask[task_mask]], s_rel[mask[task_mask]]
                if len(s_arc) > 0:
                    gold_arc, gold_rel = arcs[task_mask][mask[task_mask]
                                                        ], rels[task_mask][mask[task_mask]]

                    loss += self.get_loss(s_arc, s_rel, gold_arc, gold_rel)
                    
                    pred_arcs, pred_rels = self.decode(s_arc, s_rel)
                    metric(pred_arcs, pred_rels, gold_arc, gold_rel)

        loss /= len(loader)
        return loss, metric

    @torch.no_grad()
    def predict(self, loader):
        self.parser.eval()

        all_arcs, all_rels = [], []
        for words, chars in loader:
            mask = words.ne(self.vocab.pad_index)
            # ignore the first token of each sentence
            mask[:, 0] = 0
            lens = mask.sum(dim=1).tolist()
            s_arc, s_rel = self.parser(words, chars)
            s_arc, s_rel = s_arc[mask], s_rel[mask]
            pred_arcs, pred_rels = self.decode(s_arc, s_rel)

            all_arcs.extend(torch.split(pred_arcs, lens))
            all_rels.extend(torch.split(pred_rels, lens))
        all_arcs = [seq.tolist() for seq in all_arcs]
        all_rels = [self.vocab.id2rel(seq) for seq in all_rels]

        return all_arcs, all_rels

    def get_loss(self, s_arc, s_rel, gold_arcs, gold_rels):
        s_rel = s_rel[torch.arange(len(s_rel)), gold_arcs]

        arc_loss = self.criterion(s_arc, gold_arcs)
        rel_loss = self.criterion(s_rel, gold_rels)
        loss = arc_loss + rel_loss

        return loss

    def decode(self, s_arc, s_rel):
        pred_arcs = s_arc.argmax(dim=-1)
        pred_rels = s_rel[torch.arange(len(s_rel)), pred_arcs].argmax(dim=-1)

        return pred_arcs, pred_rels
