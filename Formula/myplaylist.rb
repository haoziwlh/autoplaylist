class Myplaylist < Formula
  desc "AI-powered music playlist generator and player"
  homepage "https://github.com/haoziwlh/autoplaylist"
  url "https://files.pythonhosted.org/packages/a4/ae/579ca805012d996bc075aa884a2f00d5b6e409a3da5ace51587ce855fe79/myplaylist-0.3.7-py3-none-any.whl",,,,,,,,,
      using: :nounzip
  sha256 "6325444f65d6f7d044f20b7f9aced484ace5e4b7b7858563b0eacf3d36a41cc7"
  license "MIT"

  depends_on "python@3.11"
  depends_on "mpv"

  def install
    venv = libexec/"venv"
    system Formula["python@3.11"].opt_bin/"python3.11", "-m", "venv", venv
    system venv/"bin/pip", "install", "myplaylist==#{version}"
    bin.install_symlink venv/"bin/myplaylist"
  end

  test do
    assert_match "myplaylist", shell_output("#{bin}/myplaylist --help")
  end
end
