#pragma once
// Mallik: semantic backend lives behind this interface.
// Start with pretrained ONNX (SalsaNext/FRNet/Cylinder3D); no custom training.
struct LidarFrame;
struct SemanticFrame;
class SemanticProvider {
 public:
  virtual ~SemanticProvider() = default;
  virtual SemanticFrame infer(const LidarFrame& scan) = 0;
};
