import argparse
import warnings
import multiprocessing
import pickle
import numpy as np
import pandas as pd
import torch
import torch.nn.functional as F
from importlib import import_module
from tqdm import tqdm
import albumentations as A
from albumentations.pytorch import ToTensorV2
from dataset import CustomDataset
from train import collate_fn


def predict(model, test_loader, device):
    size = 256
    transform = A.Compose([A.Resize(size, size)])
    print('Start prediction.')

    model.eval()

    file_name_list = []
    preds_array = np.empty((0, size*size), dtype=np.long)

    with torch.no_grad():
        for _, (imgs, image_infos) in enumerate(tqdm(test_loader)):

            # inference (512 x 512)
            outs = model(torch.stack(imgs).to(device))
            oms = torch.argmax(outs.squeeze(), dim=1).detach().cpu().numpy()

            # resize (256 x 256)
            temp_mask = []
            for img, mask in zip(np.stack(imgs), oms):
                transformed = transform(image=img, mask=mask)
                mask = transformed['mask']
                temp_mask.append(mask)

            oms = np.array(temp_mask)

            oms = oms.reshape([oms.shape[0], size*size]).astype(int)
            preds_array = np.vstack((preds_array, oms))

            file_name_list.append([i['file_name'] for i in image_infos])
    print("End prediction.")
    file_names = [y for x in file_name_list for y in x]

    return file_names, preds_array


def predict_proba(model, test_loader, device):
    model.eval()
    preds_list = []
    with torch.no_grad():
        for _, (imgs, _) in enumerate(tqdm(test_loader)):

            outs = model(torch.stack(imgs).to(device))
            outs = outs.squeeze()
            outs = F.softmax(outs, dim=0)
            outs = outs.detach().cpu().numpy()
            logits.append(outs)

    return preds_list


if __name__ == '__main__':
    parser = argparse.ArgumentParser()

    parser.add_argument('--batch_size', type=int, default=8, help='input batch size for training (default: 8)')
    parser.add_argument('--model', type=str, default='base', help='model type (default: base)')
    parser.add_argument('--data_dir', type=str, default='../../data')
    parser.add_argument('--output_name', type=str, default='output')
    parser.add_argument('--test_json', type=str, default='test.json')
    parser.add_argument('--model_dir', type=str, default='./saved/exp/latest.pt')
    parser.add_argument('--get_proba', action='store_true')

    args = parser.parse_args()

    warnings.filterwarnings(action='ignore')

    device = "cuda" if torch.cuda.is_available() else "cpu"
    num_workers = multiprocessing.cpu_count() // 2

    model = getattr(import_module("model"), args.model)

    # best model 불러오기
    checkpoint = torch.load(args.model_dir, map_location=device)
    state_dict = checkpoint.state_dict()
    model.load_state_dict(state_dict)

    model = model.to(device)


    # test dataset
    test_transform = A.Compose(
        [
            ToTensorV2(),
        ]
    )
    dataset_path = args.data_dir
    test_dataset = CustomDataset(dataset_path, args.test_json, mode='test',
                                 transform=test_transform)

    if args.get_proba is not None:
        test_loader = torch.utils.data.DataLoader(dataset=test_dataset,
                                                  batch_size=1,
                                                  num_workers=num_workers,
                                                  collate_fn=collate_fn)
        logits = predict_proba(model, test_loader, device)
        output_name = f'{args.output_name}.pickle'
        with open(output_name, 'wb') as f:
            pickle.dump(logits, f, pickle.HIGHEST_PROTOCOL)
    else:
        test_loader = torch.utils.data.DataLoader(dataset=test_dataset,
                                                  batch_size=args.batch_size,
                                                  num_workers=num_workers,
                                                  collate_fn=collate_fn)

        # sample_submisson.csv 열기
        submission = pd.read_csv('../submission/sample_submission.csv', index_col=None)

        # test set에 대한 prediction
        file_names, preds = predict(model, test_loader, device)

        # PredictionString 대입
        for file_name, string in zip(file_names, preds):
            submission = submission.append(
                    {"image_id": file_name, "PredictionString": ' '.join(str(e) for e in string.tolist())},
                    ignore_index=True)

        output_name = f'../submission/{args.output_name}.csv'
        submission.to_csv("../submission/output.csv", index=False)
