#include <cstdio>

int main() {
  std::fputs(
      "veyra_live unavailable: no ROS2/live-LiDAR adapter public interface is installed; "
      "the local dataset player remains available via veyra_player.\n",
      stderr);
  return 3;
}
